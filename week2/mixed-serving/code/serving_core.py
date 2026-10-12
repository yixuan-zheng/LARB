"""Torch-free core of the mixed prefill+decode serving loop.

Why this module exists
----------------------
The Week 2 harness needs two executors of *the same* schedule: a measured one
(real Gemma 3n forwards on one L40S, ``serving_lib``) and a simulated one that
replays measured per-forward costs on CPU (``cost_table``).  If the two
executors each grew their own loop, the comparison between them would be a
comparison of two different schedulers.  So admission, batching, budget
accounting, per-request timestamps, SLO bookkeeping and the iteration log all
live here, with no torch import, and the executors only answer one question:

    "execute this plan and tell me how long it took, and which tokens came out"

Design notes (see week2/mixed-serving/README.md)
-----------------------------------------------
* One **batch = one forward = one FFN width**.  A mixed-width batch is
  unsupported by the mechanism, so the scheduler never proposes one; the width
  policy returns exactly two plans per iteration (one for the prefill batch,
  one for the decode batch).  An iteration may therefore perform *one* switch
  (the prefill/decode boundary switch of the phase hybrid).
* Prefill and decode of different requests are executed sequentially inside an
  iteration rather than fused into one kernel launch.  This is the one
  deliberate fidelity approximation of the harness: it cannot change the total
  prefill/decode *work*, only the overlap, and it keeps the width-per-batch
  invariant honest instead of inventing a mixed-width kernel.
* A request that finishes prefill inside an iteration emits its first token at
  the end of that prefill forward and does **not** also decode in the same
  iteration (the Week 1 quality convention: step 0 is the prefill and it
  produces answer token 0).
* Generation length is forced to the trace's ``output_tokens`` and greedy
  argmax is used, so every configuration generates the same number of tokens
  for the same request.  This is the convention the Azure LLM inference dataset
  documents for its own replay ("force the model to generate the corresponding
  number of output tokens for each request"), and it removes output length as a
  confound between widths.
* The policy never sees ``output_tokens``: ``EngineView`` is built explicitly
  and carries only information an online server would have.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


# --------------------------------------------------------------------------- #
# Clocks
# --------------------------------------------------------------------------- #
class WallClock:
    """Monotonic host clock; ``advance_to`` sleeps (idle server waiting for load)."""

    name = "wall"

    def __init__(self) -> None:
        import time

        self._time = time
        self._origin = time.perf_counter()

    def now(self) -> float:
        return self._time.perf_counter() - self._origin

    def advance_to(self, t: float) -> None:
        delay = t - self.now()
        if delay > 0:
            self._time.sleep(delay)


class VirtualClock:
    """Simulation clock advanced by the executor's reported durations."""

    name = "virtual"

    def __init__(self, start: float = 0.0) -> None:
        self._now = float(start)

    def now(self) -> float:
        return self._now

    def advance_to(self, t: float) -> None:
        self._now = max(self._now, float(t))


# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EngineConfig:
    """Scheduling budget.  Widths are *not* here: they belong to the policy."""

    #: Max new tokens (prefill + decode) scheduled in one iteration.
    token_budget: int = 4096
    #: Max new prefill tokens scheduled in one iteration.
    prefill_token_budget: int = 2048
    #: Max requests advanced one decode step per iteration (= decode batch cap).
    decode_batch_cap: int = 64
    #: Prefill chunk size in tokens; 0 means "whole remaining prompt in one forward".
    prefill_chunk: int = 0
    #: Max requests sharing one prefill forward.  The GPU executor implements only 1
    #: (padded prefill batching is deliberately unimplemented: batch-1 prefill is
    #: measured faster per prompt token here).  The scheduler still honours the field,
    #: so a future executor can raise it.
    prefill_batch_cap: int = 1
    #: Padded prefill batches are rounded up to a multiple of this many tokens.
    pad_bucket: int = 128
    #: Hard cap on concurrently admitted (running) requests.
    max_running: int = 96
    #: Demand: a request whose total sequence would exceed this is refused.
    max_seq_len: int = 8192
    #: Recorded in the manifest, not used by the loop.
    seed: int = 6222

    def validate(self) -> None:
        for name in ("token_budget", "prefill_token_budget", "decode_batch_cap",
                     "prefill_batch_cap", "pad_bucket", "max_running", "max_seq_len"):
            if int(getattr(self, name)) < 1:
                raise ValueError(f"EngineConfig.{name} must be >= 1")
        if int(self.prefill_chunk) < 0:
            raise ValueError("EngineConfig.prefill_chunk must be >= 0")
        # ``token_budget`` caps the iteration as a whole, so a prefill or decode
        # budget larger than it simply means "may use the whole iteration" and is
        # not an error.  The scheduler enforces the smaller of the two.

    def to_dict(self) -> dict:
        return {name: getattr(self, name) for name in self.__dataclass_fields__}


# --------------------------------------------------------------------------- #
# Per-request state
# --------------------------------------------------------------------------- #
@dataclass
class ReqState:
    """One in-flight request.  Timestamps are in clock seconds (see README)."""

    request_id: str
    arrival_s: float
    prompt_tokens: int
    #: Trace truth.  NEVER exposed to the policy (see ``EngineView``).
    output_tokens_target: int
    admitted_s: "float | None" = None
    prefill_pos: int = 0
    prefill_started_s: "float | None" = None
    prefill_widths: list = field(default_factory=list)
    decode_widths: list = field(default_factory=list)
    token_times: list = field(default_factory=list)
    generated: int = 0
    last_token_s: "float | None" = None
    finished_s: "float | None" = None
    rejected_reason: "str | None" = None
    #: Hash (and preview) of the generated token ids, for the quality layer.
    token_hash: str = ""
    token_preview: str = ""

    @property
    def prefill_done(self) -> bool:
        return self.prefill_pos >= self.prompt_tokens

    @property
    def finished(self) -> bool:
        return self.generated >= self.output_tokens_target

    @property
    def first_token_s(self) -> "float | None":
        return self.token_times[0] if self.token_times else None

    def step_widths(self) -> list:
        """Width per *generated step*: index 0 is the prefill, k>=1 decode step k-1.

        Matches ``week1/quality/code/schedules.py`` exactly, so a width history
        recorded here can be scored by the frozen quality harness.
        """
        if not self.prefill_widths:
            return []
        return [self.prefill_widths[-1]] + list(self.decode_widths)

    def outcome(self) -> dict:
        gaps = [b - a for a, b in zip(self.token_times, self.token_times[1:])]
        ttft = (self.token_times[0] - self.arrival_s) if self.token_times else None
        return {
            "request_id": self.request_id,
            "arrival_s": self.arrival_s,
            "admitted_s": self.admitted_s,
            "prompt_tokens": self.prompt_tokens,
            "output_tokens": self.generated,
            "output_tokens_target": self.output_tokens_target,
            "prefill_chunks": len(self.prefill_widths),
            "ttft_s": ttft,
            "itl_s": gaps,
            "max_itl_s": max(gaps) if gaps else None,
            "mean_tpot_s": (sum(gaps) / len(gaps)) if gaps else None,
            "e2e_s": (self.finished_s - self.arrival_s) if self.finished_s else None,
            "finished": bool(self.finished),
            "rejected_reason": self.rejected_reason,
            "prefill_widths": list(self.prefill_widths),
            "decode_widths": list(self.decode_widths),
            "switches": count_switches(self.step_widths()),
            "token_hash": self.token_hash,
            "token_preview": self.token_preview,
        }


def make_iteration_log(*, iteration, t_start_s, t_end_s, gpu_ms, host_ms, plan,
                       prefill_groups, prefill_widths, decode_width, switches,
                       switch_apply_ms, waiting, running, completed, mode, unstarted=0,
                       decode_backlog=0, cache_rebuild_ms=0.0, note="") -> dict:
    """The iteration record, built in one place so both executors emit identical fields.

    ``mode`` is ``"measured"`` for real forwards and ``"replay"`` for the cost-table
    cross-check; a results table without a mode column is impossible by construction.

    Two backlog signals are recorded because a saturated server shows pressure in
    either of them:

    * ``unstarted`` - arrived requests that have not begun prefill (admitted but
      waiting, or not yet admitted).  This is what the TTFT gate feels.
    * ``decode_backlog`` - prefilled, unfinished requests that this iteration had
      no room to decode.  This is what the ITL gate feels.

    Week 1's pilot produced neither, which is why it could not answer the
    overload question.
    """
    return {
        "iteration": int(iteration),
        "t_start_s": float(t_start_s),
        "t_end_s": float(t_end_s),
        "duration_s": float(t_end_s) - float(t_start_s),
        "gpu_ms": float(gpu_ms),
        "host_ms": float(host_ms),
        "cache_rebuild_ms": float(cache_rebuild_ms),
        "prefill_batches": len(prefill_groups),
        "prefill_requests": len(plan.prefill),
        "prefill_tokens": int(plan.prefill_tokens),
        "padded_prefill_tokens": int(plan.padded_prefill_tokens),
        "prefill_widths": [str(w) for w in prefill_widths],
        "decode_batch": len(plan.decode),
        "decode_tokens": len(plan.decode),
        "decode_backlog": int(decode_backlog),
        "decode_width": decode_width,
        "switches": int(switches),
        "switch_apply_ms": float(switch_apply_ms),
        "waiting": int(waiting),
        "unstarted": int(unstarted),
        "running": int(running),
        "completed": int(completed),
        "queue_depth": int(waiting) + int(running),
        "mode": mode,
        "note": note,
    }


def unstarted_count(waiting, running) -> int:
    """Arrived requests that have not begun prefill (see ``make_iteration_log``)."""
    return len(waiting) + sum(1 for r in running if r.prefill_started_s is None)


def backlog_counts(state, plan) -> tuple:
    """``(unstarted, decode_backlog)`` for the iteration about to be logged."""
    unstarted = unstarted_count(state.waiting, state.running)
    ready = sum(1 for r in state.running if r.prefill_done and not r.finished)
    return unstarted, max(0, ready - len(plan.decode))


class StateApplierMixin:
    """Shared, executor-independent bookkeeping for prefill chunks and decode steps.

    Both executors keep ``self.states = {request_id: ReqState}`` (filled in
    ``on_admit``) and call these two methods with the clock time at which the
    corresponding forward *finished*.  A request's ``token_times`` entry is
    therefore the emission time of the token that forward produced, which is what
    TTFT and ITL are defined on.  Keeping this shared is what stops the measured
    loop and the replay cross-check from drifting apart in their accounting.
    """

    states: dict

    def apply_prefill(self, plan, t_start: float, t_end: float) -> None:
        for group in plan.prefill_groups:
            for a in group:
                st = self.states[a.request_id]
                st.prefill_widths.append(plan.prefill_width)
                st.prefill_pos += int(a.chunk_len)
                if st.prefill_started_s is None:
                    st.prefill_started_s = float(t_start)
                if a.completes:
                    st.token_times.append(float(t_end))
                    st.generated += 1
                    st.last_token_s = float(t_end)

    def apply_decode(self, plan, t_end: float) -> None:
        for rid in plan.decode:
            st = self.states[rid]
            st.decode_widths.append(plan.decode_width)
            st.token_times.append(float(t_end))
            st.generated += 1
            st.last_token_s = float(t_end)


def accounting_check(state) -> dict:
    """Check every invariant the loop claims, on a finished run.

    Lives here (torch-free) rather than in ``validate_harness`` so that *every* run
    can self-validate, including CPU replay runs, without importing torch for the
    check itself.  ``validate_harness.gate_accounting`` is a thin wrapper over it.
    """
    problems = []
    for r in state.completed:
        outcome = r.outcome()
        if len(r.token_times) != r.generated:
            problems.append(f"{r.request_id}: {len(r.token_times)} timestamps vs "
                            f"{r.generated} tokens")
        if len(r.prefill_widths) < 1:
            problems.append(f"{r.request_id}: no prefill width recorded")
        if len(r.decode_widths) != max(0, r.generated - 1):
            problems.append(f"{r.request_id}: {len(r.decode_widths)} decode widths vs "
                            f"{r.generated - 1} decode tokens")
        if len(r.step_widths()) != r.generated:
            problems.append(f"{r.request_id}: step_widths length "
                            f"{len(r.step_widths())} != {r.generated}")
        if r.generated != r.output_tokens_target:
            problems.append(f"{r.request_id}: generated {r.generated} != trace "
                            f"{r.output_tokens_target}")
        if r.prefill_pos != r.prompt_tokens:
            problems.append(f"{r.request_id}: prefilled {r.prefill_pos} of "
                            f"{r.prompt_tokens} prompt tokens")
        if any(b < a for a, b in zip(r.token_times, r.token_times[1:])):
            problems.append(f"{r.request_id}: token timestamps are not monotone")
        if outcome["ttft_s"] is not None and outcome["ttft_s"] <= 0:
            problems.append(f"{r.request_id}: non-positive TTFT")
    for it in state.iterations:
        if abs(it["duration_s"] - max(0.0, it["t_end_s"] - it["t_start_s"])) > 1e-9:
            problems.append(f"iteration {it['iteration']}: duration != t_end - t_start")
    return {"passed": not problems, "n_requests": len(state.completed),
            "n_iterations": state.iteration, "problems": problems[:20],
            "n_problems": len(problems)}


def count_switches(width_seq) -> int:
    return sum(1 for a, b in zip(width_seq, width_seq[1:]) if a != b)


# --------------------------------------------------------------------------- #
# Policy-visible view (no future knowledge)
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class EngineView:
    """Everything the width policy may see.  Deliberately no ``output_tokens``.

    ``waiting_prompts`` are prompt lengths of requests that have arrived and
    been admitted but not yet prefilled; ``running`` is a tuple of
    ``(generated_so_far, current_width, arrival_s)``.  ``queue_depth`` counts
    arrived-but-unfinished requests, the load signal an online policy can
    actually observe.
    """

    now_s: float
    iteration: int
    slo_ttft_s: float
    slo_itl_s: float
    waiting_prompts: tuple
    running: tuple
    queue_depth: int
    admitted: int
    completed: int

    def __post_init__(self) -> None:
        for name in ("output_tokens", "output_tokens_target", "remaining"):
            if hasattr(self, name):
                raise ValueError(f"EngineView must not expose {name!r}")


# --------------------------------------------------------------------------- #
# Plans
# --------------------------------------------------------------------------- #
@dataclass
class PrefillAssignment:
    request_id: str
    chunk_len: int
    #: True when this chunk completes the prompt (and therefore emits token 0).
    completes: bool
    #: ``chunk_len`` rounded up to the batch's padding bucket (0 until grouped).
    padded_len: int = 0


@dataclass
class SchedulerPlan:
    """One iteration: a prefill batch, a decode batch, and one width each."""

    prefill: list = field(default_factory=list)
    decode: list = field(default_factory=list)
    prefill_width: "str | None" = None
    decode_width: "str | None" = None
    #: Padded prefill batches, one inner list per forward (all share a width).
    prefill_groups: list = field(default_factory=list)
    #: Set when nothing could be scheduled (executor idle / wait for arrivals).
    reason: str = ""

    @property
    def prefill_tokens(self) -> int:
        return sum(a.chunk_len for a in self.prefill)

    @property
    def padded_prefill_tokens(self) -> int:
        return sum(a.padded_len for a in self.prefill)

    def is_empty(self) -> bool:
        return not self.prefill and not self.decode


# --------------------------------------------------------------------------- #
# Scheduling
# --------------------------------------------------------------------------- #
def build_view(now_s, iteration, running, waiting, completed, slo) -> EngineView:
    """Construct the policy-visible view.  The only place a view is made."""
    ready = [r for r in running if r.prefill_done and not r.finished]

    def current_width(r):
        seq = r.prefill_widths + r.decode_widths
        return seq[-1] if seq else None

    return EngineView(
        now_s=float(now_s),
        iteration=int(iteration),
        slo_ttft_s=float(slo.ttft_s),
        slo_itl_s=float(slo.itl_gate_s),
        waiting_prompts=tuple(r.prompt_tokens for r in waiting),
        running=tuple((r.generated, current_width(r), r.arrival_s) for r in ready),
        queue_depth=len(waiting) + len(running),
        admitted=len(running),
        completed=int(completed),
    )


class Scheduler:
    """FIFO admission, FIFO-with-stickiness prefill, longest-waiting-first decode.

    Every configuration shares this scheduler; only the width policy differs, so
    no configuration can win by being scheduled differently.  The three rules:

    * **Admission** is arrival order (a real server's queue).
    * **Prefill** is arrival order, but a request that has already started
      (chunked prefill) keeps its turn, so chunking cannot starve it.  Selection
      stops at ``prefill_token_budget`` (real, unpadded tokens) and
      ``prefill_batch_cap`` requests.
    * **Decode** is ordered by the time since that request's last token
      (``last_token_s``), i.e. round-robin on the metric the ITL SLO measures.
    """

    def __init__(self, config: EngineConfig):
        self.config = config

    # -- selection ---------------------------------------------------------- #
    def _select_prefill(self, running) -> list:
        need = [r for r in running if not r.prefill_done]
        # Stickiness first (a started chunked prefill keeps its turn), then FIFO.
        need.sort(key=lambda r: (r.prefill_started_s is None, r.arrival_s, r.request_id))
        budget, chosen = int(self.config.prefill_token_budget), []
        for r in need:
            if len(chosen) >= self.config.prefill_batch_cap or budget <= 0:
                break
            remaining = r.prompt_tokens - r.prefill_pos
            chunk = remaining if self.config.prefill_chunk == 0 \
                else min(int(self.config.prefill_chunk), remaining)
            chunk = min(chunk, budget)
            if chunk <= 0:
                break
            chosen.append(PrefillAssignment(r.request_id, chunk, chunk == remaining))
            budget -= chunk
        return chosen

    def _select_decode(self, running, prefill_ids, cap: int) -> list:
        ready = [r for r in running if r.prefill_done and not r.finished
                 and r.request_id not in prefill_ids]
        ready.sort(key=lambda r: (r.last_token_s if r.last_token_s is not None else -1.0,
                                  r.arrival_s, r.request_id))
        return ready[: max(0, int(cap))]

    # -- the plan for one iteration ----------------------------------------- #
    def plan(self, running, now_s, iteration, completed, policy, slo,
             waiting=()) -> SchedulerPlan:
        """Decide one iteration.

        ``waiting`` is the arrived-but-not-yet-admitted queue: it is not schedulable,
        but an online policy must be able to *see* it, so it goes into the view's
        queue depth (the load signal) while only ``running`` can be scheduled.
        """
        prefill = self._select_prefill(running)
        used = sum(a.chunk_len for a in prefill)
        decode_cap = min(int(self.config.decode_batch_cap),
                         max(0, int(self.config.token_budget) - used))
        decode = self._select_decode(running, {a.request_id for a in prefill}, decode_cap)
        view = build_view(now_s, iteration, running, waiting, completed, slo)
        if not prefill and not decode:
            return SchedulerPlan(reason="idle")
        plan = SchedulerPlan(prefill=prefill, decode=[r.request_id for r in decode])
        if prefill:
            plan.prefill_width = policy.prefill_width(view)
            plan.prefill_groups = _group_prefill(prefill, self.config)
        if decode:
            plan.decode_width = policy.decode_width(view)
        return plan


def _group_prefill(assignments, config: EngineConfig) -> list:
    """Split the selected prefills into padded batches, one forward per batch.

    Members of a batch share a rounded chunk length, so a forward pads every row
    to the batch maximum.  The bucket is capped at the largest chunk actually
    selected: when prefill is chunked, padding a 64-token chunk to 256 tokens
    would add compute and buy nothing (the chunked-prefill sanity check in the CPU
    tests measures exactly this as ``padding_waste``).
    """
    if not assignments:
        return []
    cap = max(1, int(config.prefill_batch_cap))
    bucket = max(1, min(int(config.pad_bucket), max(a.chunk_len for a in assignments)))
    by_len = {}
    for a in assignments:
        by_len.setdefault(int(math.ceil(a.chunk_len / bucket) * bucket), []).append(a)
    groups = []
    for padded_len in sorted(by_len):
        members = by_len[padded_len]
        for offset in range(0, len(members), cap):
            group = members[offset:offset + cap]
            for a in group:
                a.padded_len = padded_len
            groups.append(group)
    return groups


# --------------------------------------------------------------------------- #
# The shared serving loop
# --------------------------------------------------------------------------- #
@dataclass
class RunState:
    """Mutable state of one serving run."""

    running: list = field(default_factory=list)
    waiting: list = field(default_factory=list)
    completed: list = field(default_factory=list)
    rejected: list = field(default_factory=list)
    iterations: list = field(default_factory=list)
    arrivals: list = field(default_factory=list)
    finished_arrivals: bool = False
    iteration: int = 0
    peak_running: int = 0
    vram_deferred: int = 0
    switches_applied: int = 0
    wall_s: float = 0.0
    origin_s: float = 0.0
    trace_span_s: float = 0.0
    request_count: int = 0

    def all_done(self) -> bool:
        return self.finished_arrivals and not self.running and not self.waiting


def run_loop(executor, trace, config, policy, slo, clock, max_iterations: int = 1000000,
             progress=None) -> RunState:
    """Drive one trace to completion through ``executor``.

    The loop is deliberately executor-agnostic: ``serving_lib.GpuExecutor`` runs
    real forwards, ``cost_table.ReplayExecutor`` looks the same forwards up in a
    measured cost table.  Everything else - admission, budgets, timestamps,
    iteration logs - is identical by construction.
    """
    config.validate()
    state = RunState()
    arrivals = list(trace.requests)
    idx = 0
    origin = clock.now()

    while not state.all_done():
        if state.iteration >= max_iterations:
            raise RuntimeError(f"iteration cap {max_iterations} reached; queue is not draining")
        now = clock.now()
        # -- arrivals ------------------------------------------------------ #
        while idx < len(arrivals) and origin + arrivals[idx]["arrival_s"] <= now:
            req = arrivals[idx]
            total = int(req["prompt_tokens"]) + int(req["output_tokens"])
            r = ReqState(
                request_id=str(req.get("request_id", f"r{idx}")),
                arrival_s=origin + float(req["arrival_s"]),
                prompt_tokens=int(req["prompt_tokens"]),
                output_tokens_target=int(req["output_tokens"]),
            )
            if total > config.max_seq_len:
                r.rejected_reason = f"sequence {total} > max_seq_len {config.max_seq_len}"
                r.finished_s = now
                state.rejected.append(r)
            else:
                state.waiting.append(r)
            idx += 1
        if idx >= len(arrivals):
            state.finished_arrivals = True

        # -- admission ----------------------------------------------------- #
        # FIFO; stops on the running cap or a refused VRAM estimate (which is a
        # deferral, not a drop: the request stays at the head of the queue).
        while state.waiting and len(state.running) < config.max_running:
            head = state.waiting[0]
            if not executor.can_admit(state.running, head, config):
                state.vram_deferred += 1
                break
            state.waiting.pop(0)
            head.admitted_s = clock.now()
            state.running.append(head)
            executor.on_admit(head, config)

        # -- decide and execute one iteration ------------------------------ #
        plan = executor.scheduler.plan(state.running, clock.now(), state.iteration,
                                       len(state.completed), policy, slo,
                                       waiting=state.waiting)
        if plan.is_empty():
            if state.waiting or state.running:
                raise RuntimeError(
                    "scheduler produced an empty plan while work is outstanding "
                    f"(running={len(state.running)}, waiting={len(state.waiting)})")
            if idx < len(arrivals):
                clock.advance_to(origin + arrivals[idx]["arrival_s"])
                continue
            break
        result = executor.execute(plan, state, config, clock)
        state.iteration += 1
        state.peak_running = max(state.peak_running, len(state.running))
        state.switches_applied += int(result.get("switches", 0))
        state.iterations.append(result["log"])
        if progress is not None and state.iteration % progress == 0:
            print(f"[loop] iter={state.iteration} t={clock.now() - origin:8.1f}s "
                  f"running={len(state.running)} waiting={len(state.waiting)} "
                  f"done={len(state.completed)}", flush=True)
        # -- retire -------------------------------------------------------- #
        keep = []
        for r in state.running:
            if r.finished:
                r.finished_s = clock.now()
                state.completed.append(r)
                executor.on_retire(r)
            else:
                keep.append(r)
        state.running = keep

    state.wall_s = clock.now() - origin
    state.origin_s = origin
    state.trace_span_s = (arrivals[-1]["arrival_s"] if arrivals else 0.0)
    state.request_count = len(arrivals)
    return state
