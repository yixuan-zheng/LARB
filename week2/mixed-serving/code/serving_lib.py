"""Real-GPU executor for the mixed prefill+decode loop (the harness's primary evidence).

What this module is
-------------------
``serving_core`` owns the schedule; this module owns the forwards.  It reuses the
frozen Week 1 instruments instead of re-deriving them: ``latency_lib.Timer`` (wall +
CUDA-event), ``clock_ramp``/``wait_for_sm_clock`` (the L40S idles at ~210 MHz SM),
``RunRecord``/``base_manifest`` (crash-safe records with provenance),
``vram_budget_check`` (capacity), ``latency_math.kv_resident_bytes`` (KV arithmetic),
``build_worker`` (worker construction) and ``dynamic_lib.SwitchController`` (the
per-iteration FFN width, measured in Week 1 at ~87 us host apply for all 35 layers,
numerically exact at `max_abs_logit 0.0`).

The three decisions that matter
-------------------------------
1. **One model, three configurations.**  Every configuration runs the *same*
   resident switchable full-weight model and differs only in the width plan it
   applies.  That removes model-build, load-order, VRAM and dynamic-path overhead
   as explanations for any difference, and makes the comparison a comparison of
   schedules.  ``static_large``/``static_small`` are therefore "the switchable model
   pinned at one width", and Week 1's S8 gate (dynamic-at-W == static-W) is the
   justification.  Static reference workers are available for a cross-check.
2. **Prefill is batch-1 by default.**  Measured in this runtime: a 2048-token
   prefill costs 160.1 ms at batch 1 but 811.0 ms at batch 4 (8192 tokens), i.e.
   12.8k vs 10.1k prompt tokens/s.  Batching prefill is *slower per token* here, so
   the default takes the faster, simpler path (one request per prefill forward, no
   padding, no positional subtleties).  ``prefill_batch_cap > 1`` enables a padded
   batch and is gated by ``validate_harness.batch_equivalence``.
3. **Decode is batched**, because decode step time is flat in batch (54.9 ms at
   batch 1 and 74.1 ms at batch 64 / context 2048), so batching decode is where the
   throughput is.  Batched decode with per-request KV lengths needs a common cache
   length, so each iteration left-pads the rows' caches to the batch maximum and
   passes **per-row ``position_ids``** (Gemma3n honours explicit position_ids; its
   default is ``arange(q_len) + past_seen_tokens``, which is only correct for
   uniform rows).  The rebuild cost is *measured* and reported per iteration as
   ``cache_rebuild_ms``; it applies to every configuration, and a production paged
   server would not pay it -- so absolute throughput here is conservative and the
   per-iteration record says exactly where the time went.

Generation is greedy with the trace's forced output length, per the Azure dataset's
own replay convention, so the three configurations generate identical token counts.
"""
from __future__ import annotations

import hashlib
import sys
import time
from pathlib import Path

import torch

import serving_core as core

# --- Week 1 infrastructure (frozen; imported, never copied) ----------------- #
_WEEK1 = Path(__file__).resolve().parents[3] / "week1" / "latency-baselines"
if str(_WEEK1) not in sys.path:
    sys.path.insert(0, str(_WEEK1))

import latency_lib as lib  # noqa: E402  (the frozen instrument suite)
import switch_schedules as sched  # noqa: E402  (WidthPlan algebra)

PRESET_NAMES = ("large", "small", "medium")


class CpuTimer:
    """``latency_lib.Timer`` interface without CUDA events (CPU smoke tests)."""

    def __init__(self, pool: int = 2):
        self._pool = pool

    def time(self, fn):
        t0 = time.perf_counter()
        out = fn()
        return out, 1000.0 * (time.perf_counter() - t0), 0.0


def make_timer(device: str):
    return lib.Timer() if str(device).startswith("cuda") else CpuTimer()


def pair_to_cache(pairs, template=None):
    """Build an HF cache object whose per-layer K/V are exactly ``pairs``.

    ``template`` **must** be a real cache object returned by the model (the harness
    keeps one per request): Gemma 3n mixes sliding-window and global attention, and
    that per-layer flag lives on the cache's layer objects, not on the tensors.  A
    cache built from scratch therefore tells the model every layer is global, and the
    logits change -- measured, not theorised: with a self-built cache the second token
    of a 24-token prompt differed from the stock path (`[18649, 258484, 197244]` vs
    `[18649, 258486, 175135]`), while the same cache with the template's flags
    reproduces the stock path exactly.  Copying the layer objects and only replacing
    their tensors keeps every flag.
    """
    import copy as _copy

    from transformers.cache_utils import DynamicCache

    cache = DynamicCache()
    if template is not None and getattr(template, "layers", None):
        layers = []
        for layer_idx in range(len(pairs)):
            layer = _copy.copy(template.layers[layer_idx])
            layer.keys, layer.values = pairs[layer_idx]
            layers.append(layer)
        cache.layers = layers
        return cache
    # No template (should not happen after a real prefill): fall back to a plain
    # build and say so, because the resulting logits may differ as described above.
    print("[serving] WARNING: building a cache without a model template; per-layer "
          "attention flags may be wrong", flush=True)
    for layer_idx, (k, v) in enumerate(pairs):
        cache.update(torch.zeros_like(k), torch.zeros_like(v), layer_idx)
    for layer_idx, (k, v) in enumerate(pairs):
        cache.layers[layer_idx].keys = k
        cache.layers[layer_idx].values = v
    return cache


def cache_pairs(cache):
    """``[(k, v)]`` per layer, for whichever cache implementation HF returned."""
    layers = getattr(cache, "layers", None)
    if layers is not None and len(layers):
        return [(layer.keys, layer.values) for layer in layers]
    key_cache = getattr(cache, "key_cache", None)
    if key_cache is not None:
        return list(zip(key_cache, getattr(cache, "value_cache", [])))
    raise RuntimeError("unsupported cache object: neither .layers nor .key_cache")


def cache_seq_len(tensor) -> int:
    """Sequence length of a stored K/V tensor.

    HuggingFace stores cache tensors as ``[batch, heads, sequence, head_dim]``, i.e.
    the sequence axis is ``-2``.  Every helper below indexes through ``-2`` and uses
    ellipsis for the rest, so the code stays correct whatever the layout convention
    is and cannot silently slice the wrong axis.
    """
    return int(tensor.shape[-2])


def trim_last_token(pairs):
    """Drop the trailing sequence position from every layer (cache surgery helper)."""
    return [(k[..., :-1, :], v[..., :-1, :]) for k, v in pairs]


def left_pad_rows(tensors):
    """Left-pad a list of ``[1, h, L_i, d]`` tensors to a common ``L = max(L_i)``.

    Padding the sequence axis on the *left* is what lets a common-shape forward serve
    rows with different context lengths while keeping each row's real tokens at the
    end of the block (so the logits we read are the real last positions).
    """
    length = max(cache_seq_len(t) for t in tensors)
    padded = [torch.nn.functional.pad(t, (0, 0, length - cache_seq_len(t), 0))
              for t in tensors]
    return torch.cat(padded, dim=0), length


def token_hash(tokens) -> str:
    payload = ",".join(str(int(t)) for t in tokens).encode()
    return hashlib.sha256(payload).hexdigest()


def prompt_offset(request_id: str, modulus: int = 997) -> int:
    """A stable prompt-content offset derived from the request id.

    The prompt a request sees must be a deterministic function of the *request*, not
    of the order in which the engine happened to admit it: otherwise two
    configurations would serve different prompt content for the same trace request,
    which is a confound (different prompt text -> different generated tokens ->
    different decode behaviour and different quality records).  Deriving the offset
    from the id removes that dependence for good.
    """
    digest = hashlib.sha1(str(request_id).encode()).hexdigest()
    return int(digest[:8], 16) % max(1, int(modulus))


# --------------------------------------------------------------------------- #
# The GPU executor
# --------------------------------------------------------------------------- #
class GpuExecutor(core.StateApplierMixin):
    """Execute plans with real Gemma 3n forwards on one GPU (mode ``measured``)."""

    mode = "measured"

    def __init__(self, model, controller, tokenizer, config: core.EngineConfig, *,
                 device: str = "cuda", dtype=torch.bfloat16, decode_mode: str = "batched",
                 prefill_batch_cap: int | None = None, vram_budget_bytes: int | None = None,
                 verbose: bool = False):
        if decode_mode not in ("batched", "single_row"):
            raise ValueError("decode_mode must be 'batched' or 'single_row'")
        self.model = model
        self.controller = controller
        self.tokenizer = tokenizer
        self.device = device
        self.dtype = dtype
        self.decode_mode = decode_mode
        self.verbose = bool(verbose)
        if int(config.prefill_batch_cap) > 1:
            raise NotImplementedError(
                "GpuExecutor implements prefill_batch_cap=1 only: padded prefill "
                "batching needs per-query masks for Gemma3n's mixed sliding/global "
                "attention, and batch-1 prefill is measured faster per prompt token "
                "here. Build the executor with a config that keeps the cap at 1.")
        self.scheduler = core.Scheduler(config)
        self.timer = make_timer(device)
        self.states = {}
        self.rows = {}          # request_id -> {"ids", "pairs", "length"}
        self.retired_tokens = {}  # request_id -> generated token ids (for the quality layer)
        self.kv_high_water = 0
        self.cache_rebuild_ms_total = 0.0
        self.request_index = 0
        #: Test hook for the harness's own injected-delay gate (``validate_harness``).
        self.inject_decode_ms = 0.0
        self._plans = {name: sched.WidthPlan.from_preset(name) for name in PRESET_NAMES}
        self._num_layers = len(controller.layers)
        #: KV-owning layers, learned from the first real prefill (E4B: 35 text layers,
        #: 20 of which own a KV cache; the rest share it).
        self._num_kv_layers = None
        cfg = model.config.get_text_config() if hasattr(model.config, "get_text_config") \
            else model.config
        self._kv_heads = int(getattr(cfg, "num_key_value_heads", 0) or 0)
        self._head_dim = int(getattr(cfg, "head_dim", 0) or 0)
        #: Sliding-window size for the layers that use it (0 = none).  Gemma 3n mixes
        #: sliding and global attention, and the mask we must build depends on it.
        window = getattr(cfg, "sliding_window", 0)
        if isinstance(window, dict):
            window = max(int(v) for v in window.values()) if window else 0
        self._sliding_window = int(window or 0)
        self._layer_types = list(getattr(cfg, "layer_types", []) or [])
        if prefill_batch_cap is not None:
            self.scheduler.config = _replace_cap(self.scheduler.config, prefill_batch_cap)
        self.vram_budget_bytes = vram_budget_bytes

    # -- width application --------------------------------------------------- #
    def plan_for(self, name: str) -> "sched.WidthPlan":
        return self._plans[name]

    def apply_width(self, name: str) -> float:
        """Apply one width to all 35 layers and return the host-side cost in ms."""
        if name is None:
            return 0.0
        return float(self.controller.apply_timed(self.plan_for(name))["apply_ms"])

    # -- admission ----------------------------------------------------------- #
    def can_admit(self, running, head, config) -> bool:
        """KV + activation budget check; a refusal defers admission, never drops.

        Uses the frozen Week 1 helpers (``activation_bytes_estimate`` for the
        worst forward in flight, ``kv_resident_bytes`` for the resident cache), so
        the loop's memory guard is the same arithmetic the Week 1 suite validated.
        """
        if self.vram_budget_bytes is None:
            return True
        resident = sum(r.prompt_tokens + r.output_tokens_target for r in running)
        resident += head.prompt_tokens + head.output_tokens_target
        kv_bytes = resident * KV_BYTES_PER_TOKEN
        return kv_bytes <= self.vram_budget_bytes

    def on_admit(self, req, config) -> None:
        # A deterministic prompt of exactly the trace's length, whose *content* is a
        # function of the request id (see ``prompt_offset``) so two configurations
        # cannot serve different prompts for the same trace request.
        ids, digest = lib.build_prompt_ids(self.tokenizer, int(req.prompt_tokens),
                                          offset=prompt_offset(req.request_id))
        ids = ids.to(self.device)
        self.states[req.request_id] = req
        self.rows[req.request_id] = {"ids": ids, "digest": digest, "pairs": None,
                                     "cache": None, "length": 0, "logits": None,
                                     "tokens": [], "next_ids": None}

    def bind(self, config: core.EngineConfig) -> None:
        self.scheduler = core.Scheduler(config)

    def on_retire(self, req) -> None:
        row = self.rows.pop(req.request_id, None)
        if row is not None:
            self.kv_high_water = max(self.kv_high_water, int(row.get("length", 0)))
            tokens = row.get("tokens") or []
            req.token_hash = token_hash(tokens)
            req.token_preview = ",".join(str(t) for t in tokens[:8])
            self.retired_tokens[req.request_id] = list(tokens)
        self.states.pop(req.request_id, None)

    def resident_sequences(self) -> int:
        return len(self.rows)

    # -- attention masks ----------------------------------------------------- #
    def _mask_dict(self, lengths, kv_len: int):
        """Explicit additive 4-D masks for a padded batch, one per attention type.

        Gemma 3n mixes sliding-window and global attention, and HuggingFace wants a
        ``{"full_attention": ..., "sliding_attention": ...}`` mapping for that.  Passing
        a 2-D mask instead makes HF size the mask itself and it rejects the request for
        padded batches ("size of tensor a (25) must match b (49)"), so the masks are
        built here: shape ``[batch, 1, q_len=1, kv_len]``, ``0`` where a key may be
        attended and ``finfo.min`` where it may not.

        Slot ``j`` of row ``i``'s cache holds logical position ``j - (kv_len - 1 - L_i)``,
        so the logical distance from the new token (position ``L_i``) to slot ``j`` is
        ``kv_len - 1 - j`` -- independent of the row.  A row may always attend its own
        real slots and the new token; a sliding layer may additionally only see the last
        ``sliding_window`` positions, which is the condition ``j > kv_len - 1 - window``.
        """
        import torch as _torch

        dtype = self.dtype
        neg = _torch.finfo(dtype).min
        batch = len(lengths)
        mask = _torch.full((batch, 1, 1, kv_len), neg, dtype=dtype, device=self.device)
        register = _torch.arange(kv_len, device=self.device)
        for row, length in enumerate(lengths):
            real = register >= (kv_len - 1 - int(length))
            mask[row, 0, 0, real] = 0.0
        mask[:, 0, 0, kv_len - 1] = 0.0  # the new token itself is always visible
        window = int(self._sliding_window or 0)
        if window <= 0:
            return {"full_attention": mask, "sliding_attention": mask}
        sliding = _torch.full((batch, 1, 1, kv_len), neg, dtype=dtype, device=self.device)
        allowed = register > (kv_len - 1 - window)
        for row, length in enumerate(lengths):
            real = register >= (kv_len - 1 - int(length))
            sliding[row, 0, 0, real & allowed] = 0.0
        sliding[:, 0, 0, kv_len - 1] = 0.0
        return {"full_attention": mask, "sliding_attention": sliding}

    # -- forwards ------------------------------------------------------------ #
    def _prefill_forward(self, assignment, width: str):
        """One request's next prefill chunk: a batch-1 forward at one width."""
        req_id = assignment.request_id
        state = self.states[req_id]
        row = self.rows[req_id]
        start = int(state.prefill_pos)
        chunk_ids = row["ids"][:, start:start + int(assignment.chunk_len)]
        self.apply_width(width)
        past = row["cache"]
        with torch.inference_mode():
            out, wall_ms, gpu_ms = self.timer.time(
                lambda: self.model(input_ids=chunk_ids, past_key_values=past,
                                   use_cache=True, logits_to_keep=1))
        row["cache"] = out.past_key_values
        pairs = cache_pairs(row["cache"])
        if self._num_kv_layers is None:
            self._num_kv_layers = len(pairs)
            if self._num_kv_layers != self._num_layers:
                print(f"[serving] KV sharing detected: {self._num_layers} text layers, "
                      f"{self._num_kv_layers} own a KV cache", flush=True)
        row["pairs"] = pairs
        row["length"] = cache_seq_len(pairs[0][0])
        if assignment.completes:
            # The first generated token comes from this forward's last position,
            # matching the frozen quality convention (step 0 is the prefill).
            row["logits"] = out.logits[:, -1, :]
        return {"wall_ms": wall_ms, "gpu_ms": gpu_ms, "pairs": pairs}

    def _prefill_group(self, group, width: str):
        """Prefill one request per forward (see the module docstring for why batch 1).

        A padded prefill batch is deliberately not implemented.  It would need
        per-query masks for Gemma3n's mixed sliding/global attention on top of the
        padding logic, and batch-1 prefill is *measured faster per prompt token* in
        this runtime (12.8k vs 10.1k tokens/s at 2048 tokens), so a padded batch would
        add correctness risk for no speed.  Calling this with more than one assignment
        is a loud error rather than a silently different schedule.
        """
        if len(group) > 1:
            raise NotImplementedError(
                "padded prefill batching is not implemented: it needs per-query masks "
                "for Gemma3n's mixed sliding/global layers, and batch-1 prefill is "
                "measured FASTER per prompt token here (12.8k vs 10.1k tok/s), so it "
                "buys nothing. Use EngineConfig(prefill_batch_cap=1).")
        return [self._prefill_forward(a, width) for a in group]

    def _decode_batched(self, rows, width: str):
        """One batched decode step with per-row padded caches and position_ids.

        All rows must present the same cache length to the model, so each row's
        real KV is left-padded to the batch maximum and hidden with the attention
        mask; ``position_ids`` restores each row's own logical position.  The pad
        slots are never computed -- only copied -- and the rebuild time is charged
        to the iteration as ``cache_rebuild_ms`` rather than hidden.
        """
        lengths = [int(self.rows[r]["length"]) for r in rows]
        rebuild_start = time.perf_counter()
        batched = []
        for layer_idx in range(len(self.rows[rows[0]]["pairs"])):
            k_batch, max_len = left_pad_rows(
                [self.rows[r]["pairs"][layer_idx][0] for r in rows])
            v_batch, _ = left_pad_rows(
                [self.rows[r]["pairs"][layer_idx][1] for r in rows])
            batched.append((k_batch, v_batch))
        mask = self._mask_dict(lengths, max_len + 1)
        position_ids = torch.tensor([[length_i] for length_i in lengths],
                                    dtype=torch.long, device=self.device)
        template = self.rows[rows[0]]["cache"]
        past = pair_to_cache(batched, template=template)
        input_ids = self._next_input_ids(rows)
        rebuild_ms = 1000.0 * (time.perf_counter() - rebuild_start)
        self.apply_width(width)
        with torch.inference_mode():
            out, wall_ms, gpu_ms = self.timer.time(
                lambda: self.model(input_ids=input_ids, attention_mask=mask,
                                   position_ids=position_ids, past_key_values=past,
                                   use_cache=True, logits_to_keep=1))
        new_pairs_cache = out.past_key_values
        new_pairs = cache_pairs(new_pairs_cache)
        tokens = out.logits[:, -1, :].argmax(-1)
        for i, r in enumerate(rows):
            row = self.rows[r]
            # Keep only this row's real slots: its L_i tokens plus the new one.
            row["pairs"] = [(k[i:i + 1, ..., max_len - lengths[i]:max_len + 1, :],
                             v[i:i + 1, ..., max_len - lengths[i]:max_len + 1, :])
                            for k, v in new_pairs]
            row["cache"] = pair_to_cache(row["pairs"], template=new_pairs_cache)
            row["length"] = lengths[i] + 1
            token = int(tokens[i])
            row["tokens"].append(token)
            row["next_ids"] = torch.tensor([[token]], dtype=torch.long, device=self.device)
        self.cache_rebuild_ms_total += rebuild_ms
        return {"wall_ms": wall_ms, "gpu_ms": gpu_ms, "rebuild_ms": rebuild_ms}

    def _decode_single(self, rows, width: str):
        """One forward per row: the reference path the batched path is compared to."""
        wall_ms = gpu_ms = 0.0
        self.apply_width(width)
        for r in rows:
            row = self.rows[r]
            length = int(row["length"])
            past = row["cache"]
            with torch.inference_mode():
                # No attention_mask and no position_ids: this row's cache is entirely
                # real, so the stock path (what HF generation itself does) is both
                # correct and the reference the gates compare against.
                out, w, g = self.timer.time(
                    lambda: self.model(input_ids=self._next_input_ids([r]),
                                       past_key_values=past, use_cache=True,
                                       logits_to_keep=1))
            wall_ms += w
            gpu_ms += g
            row["cache"] = out.past_key_values
            row["pairs"] = cache_pairs(row["cache"])
            row["length"] = length + 1
            token = int(out.logits[0, -1, :].argmax(-1))
            row["tokens"].append(token)
            row["next_ids"] = torch.tensor([[token]], dtype=torch.long, device=self.device)
        return {"wall_ms": wall_ms, "gpu_ms": gpu_ms, "rebuild_ms": 0.0}

    def _next_input_ids(self, rows):
        """The token each row is about to consume (its own last generated token)."""
        return torch.cat([self.rows[r]["next_ids"] for r in rows], dim=0)

    # -- one iteration ------------------------------------------------------- #
    def execute(self, plan, state, config, clock) -> dict:
        t_start = clock.now()
        gpu_ms = host_ms = 0.0
        rebuild_ms = 0.0
        switches_before = self.controller.n_switches
        prefill_widths = []

        for group in plan.prefill_groups:
            results = self._prefill_group(group, plan.prefill_width)
            t_end = clock.now()
            prefill_widths.append(plan.prefill_width)
            for res in results:
                gpu_ms += res["gpu_ms"]
                host_ms += max(0.0, res["wall_ms"] - res["gpu_ms"])
            one = core.SchedulerPlan(prefill=group, prefill_groups=[group],
                                     prefill_width=plan.prefill_width)
            self.apply_prefill(one, t_start, t_end)
            for a in group:
                row = self.rows[a.request_id]
                if a.completes and row.get("logits") is not None:
                    token = int(row["logits"][0].argmax(-1))
                    row["tokens"] = [token]
                    row["next_ids"] = torch.tensor([[token]], dtype=torch.long,
                                                   device=self.device)

        if plan.decode:
            fn = self._decode_batched if self.decode_mode == "batched" \
                else self._decode_single
            res = fn(list(plan.decode), plan.decode_width)
            gpu_ms += res["gpu_ms"]
            host_ms += max(0.0, res["wall_ms"] - res["gpu_ms"])
            rebuild_ms += res["rebuild_ms"]
            self.apply_decode(plan, clock.now())
            if self.inject_decode_ms:
                # Gate hook: a known extra delay the harness must be able to see.
                time.sleep(self.inject_decode_ms / 1000.0)

        switches = self.controller.n_switches - switches_before
        recent = self.controller.apply_times_ms[-switches:] if switches else []
        log = core.make_iteration_log(
            iteration=state.iteration, t_start_s=t_start, t_end_s=clock.now(),
            gpu_ms=gpu_ms, host_ms=host_ms, plan=plan, prefill_groups=plan.prefill_groups,
            prefill_widths=prefill_widths, decode_width=plan.decode_width,
            switches=switches, switch_apply_ms=float(sum(recent)),
            waiting=len(state.waiting), running=len(state.running),
            completed=len(state.completed), mode=self.mode,
            unstarted=core.unstarted_count(state.waiting, state.running),
            decode_backlog=max(0, sum(1 for r in state.running
                                      if r.prefill_done and not r.finished)
                               - len(plan.decode)),
            cache_rebuild_ms=rebuild_ms,
            note="" if not switches else "width change applied this iteration")
        return {"switches": switches, "log": log}

    # -- reporting ----------------------------------------------------------- #
    def describe(self) -> dict:
        return {
            "mode": self.mode,
            "device": self.device,
            "dtype": str(self.dtype),
            "decode_mode": self.decode_mode,
            "num_layers": self._num_layers,
            "num_kv_layers": self._num_kv_layers,
            "controller_switches": self.controller.n_switches,
            "cache_rebuild_ms_total": self.cache_rebuild_ms_total,
            "kv_high_water_tokens": self.kv_high_water,
            "resident_sequences": self.resident_sequences(),
            "vram_budget_bytes": self.vram_budget_bytes,
        }


# --------------------------------------------------------------------------- #
# Construction and the measured-run wrapper
# --------------------------------------------------------------------------- #
#: KV bytes per token, measured in Week 1 (S7: 40,960 B/token for E4B).
KV_BYTES_PER_TOKEN = 40960
#: Usable VRAM for resident KV on a 48 GiB L40S: the driver, activations and the
#: single 13.73 GiB switchable weight set leave roughly this much.
DEFAULT_VRAM_BUDGET_BYTES = 34 * 1024 ** 3


def _replace_cap(config: core.EngineConfig, cap: int) -> core.EngineConfig:
    import dataclasses

    return dataclasses.replace(config, prefill_batch_cap=max(1, int(cap)))


def build_executor(config: core.EngineConfig, *, statics=("small",), device: str = "cuda",
                   dtype=torch.bfloat16, decode_mode: str = "batched",
                   slice_mode: str = "materialize", vram_budget_bytes=None,
                   verbose: bool = True):
    """Build the switchable model + controller + executor (one resident weight set).

    ``slice_mode='materialize'`` follows Week 1's S8 finding that a materialised
    contiguous slice is the fair comparison against a static worker: ``view`` keeps
    a strided ``down_proj`` slice whose contiguity penalty would otherwise be
    mixed into the width effect.
    """
    import dynamic_lib

    dynamic, controller, static_workers, tokenizer, infos = dynamic_lib.build_switchable(
        dtype, statics=statics, device=device, verbose=verbose, slice_mode=slice_mode)
    executor = GpuExecutor(dynamic, controller, tokenizer, config, device=device,
                           dtype=dtype, decode_mode=decode_mode,
                           vram_budget_bytes=(vram_budget_bytes
                                              if vram_budget_bytes is not None
                                              else (DEFAULT_VRAM_BUDGET_BYTES
                                                    if str(device).startswith("cuda") else None)),
                           verbose=verbose)
    return executor, static_workers, tokenizer, infos


def measured_run(trace, config, policy, contract, executor, *, clock=None,
                 max_iterations: int = 200000, progress: int | None = None,
                 report_extra: dict | None = None) -> tuple:
    """Run one trace through the real loop: ``(RunState, report)``.

    The clock is a ``WallClock`` on the GPU (so idle time waiting for arrivals is
    real wall time, exactly as a server would see it) and a ``VirtualClock`` is not
    used: measured means measured.  The report is labelled ``measured`` and carries
    the executor's own accounting (cache rebuild total, controller switch count).
    """
    import slo as slo_mod

    executor.bind(config)
    clock = clock or core.WallClock()
    state = core.run_loop(executor, trace, config, policy, contract, clock,
                          max_iterations=max_iterations, progress=progress)
    report = slo_mod.summarize_run(state, contract, wall_s=state.wall_s)
    report["mode"] = "measured"
    report["executor"] = executor.describe()
    report["cache_rebuild_ms_total"] = executor.cache_rebuild_ms_total
    if report_extra:
        report.update(report_extra)
    return state, report


