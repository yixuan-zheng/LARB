"""vLLM 0.11.2 scheduler and logits-processor adapter.

This module is imported only by the GPU server. The pure contract/policy logic
lives in contract.py and policy.py and is tested on CPU.
"""
import os
import time

from vllm.v1.sample.logits_processor.interface import LogitsProcessor, MoveDirectionality
from vllm.v1.core.sched.scheduler import Scheduler

from .bus import BUS, atomic, emit, snapshot_due
from .contract import Contract, RequestControl, move_rows
from .policy import PressureTracker, choose_victim, apply_cut, pressure_threshold
from . import config

PROTOCOL = config.load_protocol()
THRESHOLD = pressure_threshold(
    int(os.environ.get("LARB_MAX_NUM_SEQS", PROTOCOL["engine"]["max_num_seqs"])),
    PROTOCOL["policy"]["pressure"]["threshold_fraction"],
    PROTOCOL["policy"]["pressure"]["threshold_minimum"],
)
PERSISTENCE = int(os.environ.get("LARB_PERSISTENCE",
                                PROTOCOL["policy"]["pressure"]["persistence_steps"]))
CUT_TARGET = PROTOCOL["policy"]["cut"]["target"]
PROGRESS_FLOOR = PROTOCOL["policy"]["cut"]["progress_floor"]
MIN_SAVING = PROTOCOL["policy"]["cut"]["min_saving"]
STRIDE = int(os.environ.get("LARB_SNAPSHOT_STRIDE", "8"))


def request_key(req):
    return req.sampling_params.extra_args["larb"]["key"]


def phase_of(key):
    return key.split("--", 1)[0]


class PressureProcessor(LogitsProcessor):
    def __init__(self, vllm_config, device, is_pin_memory):
        self.rows = {}
        self.policies = {}
        self.caps = set()
        self.trackers = {}
        emit("worker", "initialized", threshold=THRESHOLD, persistence=PERSISTENCE)

    def is_argmax_invariant(self):
        return False

    def _tracker(self, phase):
        if phase not in self.trackers:
            self.trackers[phase] = PressureTracker(THRESHOLD, PERSISTENCE)
        return self.trackers[phase]

    def update_state(self, batch_update):
        if batch_update:
            for row in batch_update.removed:
                state = self.rows.pop(row, None)
                if state is not None:
                    self.policies.pop(state.key, None)
            for row, params, prompt, output in batch_update.added:
                data = dict(params.extra_args["larb"])
                policy = data.pop("policy")
                contract = Contract(
                    name=data.pop("contract", "legacy"),
                    cue=list(data.pop("cue")),
                    close_id=data.pop("close_id"),
                    eos_id=data.pop("eos_id"),
                    answer_cap=data.pop("answer_cap"),
                    closing_brace_id=data.pop("closing_brace_id", None),
                    force_closing_brace=data.pop("force_closing_brace", False),
                ).validate()
                state = RequestControl.from_contract(
                    key=data["key"], output=output, budget=data["budget"],
                    contract=contract, arrival_ts=data.get("arrival_ts"),
                )
                self.rows[row] = state
                self.policies[state.key] = policy
                emit("worker", "admitted", key=state.key, row=row, policy=policy,
                     initial_budget=state.budget, output_object=id(output))
            for source, target, direction in batch_update.moved:
                emit("worker", "row_move", source=source, target=target,
                     direction=direction.name)
            move_rows(self.rows, [(a, b, d == MoveDirectionality.SWAP)
                                  for a, b, d in batch_update.moved])

        snapshot = BUS.get()
        waiting = snapshot.get("waiting", [])
        counts = {}
        for key in waiting:
            counts[phase_of(key)] = counts.get(phase_of(key), 0) + 1
        for phase in set(counts) | {phase_of(key) for key in self.rows}:
            self._tracker(phase).update(counts.get(phase, 0))

        by_phase = {}
        for row, state in self.rows.items():
            if self.policies.get(state.key) == "live":
                by_phase.setdefault(phase_of(state.key), []).append(state)
        for phase, states in by_phase.items():
            if not self._tracker(phase).pressure:
                continue
            victim = choose_victim(states)
            if victim is None:
                continue
            old = victim.budget
            if apply_cut(victim, CUT_TARGET):
                event = dict(key=victim.key,
                             row=next((r for r, s in self.rows.items() if s is victim), None),
                             tokens=len(victim.output), old_budget=old,
                             budget=victim.budget, waiting=counts.get(phase, 0),
                             pressure_step=snapshot.get("step"),
                             pressure_age_ms=1000 * (time.monotonic() - snapshot.get("monotonic", time.monotonic())))
                BUS.record_cut(victim.key, event)
                emit("worker", "live_reduction", **event)

    def apply(self, logits):
        for row, state in self.rows.items():
            before = state.force_start
            token = state.next_forced()
            if before is None and state.force_start is not None:
                BUS.record_cue(state.key, state.force_start, time.monotonic())
                emit("worker", "cue_started", key=state.key, tokens=state.force_start,
                     budget=state.budget, output_object=id(state.output))
            if token == state.eos_id and state.key not in self.caps:
                self.caps.add(state.key)
                reason = ("answer_cap" if state._answer_tokens() >= state.answer_cap
                          else "short_answer_closed")
                emit("worker", reason, key=state.key, tokens=len(state.output))
            if token is not None:
                logits[row].fill_(-float("inf"))
                logits[row, token] = 0
        return logits


class QueueAuditScheduler(Scheduler):
    """Observe the stock scheduler; do not change admission or batching."""

    def schedule(self):
        before = {key: req.num_computed_tokens for key, req in self.requests.items()}
        result = super().schedule()
        self.audit_step = getattr(self, "audit_step", 0) + 1
        active = []
        for key in result.num_scheduled_tokens:
            req = self.requests[key]
            active.append(dict(key=request_key(req),
                               computed_before=before.get(key, 0),
                               computed_after=req.num_computed_tokens,
                               preemptions=req.num_preemptions))
        waiting = [request_key(req) for req in self.waiting]
        snapshot = dict(step=self.audit_step, monotonic=time.monotonic(),
                        active=active, waiting=waiting,
                        running_count=len(active), waiting_count=len(waiting))
        BUS.update(snapshot)
        if snapshot_due(self.audit_step, STRIDE):
            emit("scheduler", "step", **snapshot)
        return result

