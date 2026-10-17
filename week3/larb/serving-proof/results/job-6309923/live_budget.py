"""vLLM 0.11.2 extension: atomic file mailbox -> per-request token forcing.

One GPU worker only. File polling and tracing favor auditability over speed.
No engine source changes, aborts, resubmissions, or token-prefix replay.
"""
import json
import os
from pathlib import Path
import time

from vllm.v1.sample.logits_processor.interface import LogitsProcessor, MoveDirectionality
from vllm.v1.core.sched.scheduler import Scheduler
from control import RequestControl, move_rows


def emit(stream, event, **fields):
    path = Path(os.environ['BUDGET_PROOF_DIR']) / (stream + '.jsonl')
    with path.open('a') as handle:
        handle.write(json.dumps(dict(event=event, monotonic=time.monotonic(),
                                    pid=os.getpid(), **fields)) + '\n')


class LiveBudgetProcessor(LogitsProcessor):
    def __init__(self, vllm_config, device, is_pin_memory):
        self.rows = {}
        self.control = {}
        self.stamp = None
        self.cap_reported = set()
        self.path = Path(os.environ['BUDGET_PROOF_DIR']) / 'control.json'
        emit('worker', 'processor_init')

    def is_argmax_invariant(self):
        return False

    def update_state(self, batch_update):
        if batch_update:
            for row in batch_update.removed:
                old = self.rows.pop(row, None)
                if old:
                    emit('worker', 'removed', key=old.key, row=row,
                         tokens=len(old.output), output_object=id(old.output))
            for row, params, prompt, output in batch_update.added:
                data = (params.extra_args or {}).get('live_budget')
                if data:
                    state = RequestControl(output=output, **data)
                    self.rows[row] = state
                    emit('worker', 'added', key=state.key, row=row,
                         output_object=id(output), prompt_tokens=len(prompt or []))
                else:
                    self.rows.pop(row, None)
            for source, target, direction in batch_update.moved:
                emit('worker', 'moved', source=source, target=target, direction=direction.name)
            move_rows(self.rows, [(a, b, d == MoveDirectionality.SWAP)
                                  for a, b, d in batch_update.moved])
        stamp = self.path.stat().st_mtime_ns
        if stamp != self.stamp:
            self.control = json.loads(self.path.read_text())
            self.stamp = stamp
        for row, state in self.rows.items():
            was_closed = state.close_index
            state.refresh()
            if was_closed is None and state.close_index is not None:
                emit('worker', 'thinking_closed', key=state.key, row=row,
                     close_index=state.close_index, tokens=len(state.output),
                     output_object=id(state.output), forced=state.force_start is not None)
            command = self.control.get(state.key)
            if command and command['version'] > state.version:
                changed = state.change(command['budget'], command['version'])
                emit('worker', 'budget_observed', key=state.key, row=row,
                     tokens=len(state.output), budget=state.budget,
                     accepted=changed, version=state.version,
                     output_object=id(state.output))

    def apply(self, logits):
        for row, state in self.rows.items():
            before = state.force_start
            token = state.next_forced()
            if before is None and state.force_start is not None:
                emit('worker', 'cue_started', key=state.key, row=row,
                     tokens=len(state.output), budget=state.budget,
                     output_object=id(state.output))
            if token is not None:
                if token == state.eos_id and state.key not in self.cap_reported:
                    self.cap_reported.add(state.key)
                    emit('worker', 'answer_cap_forced', key=state.key,
                         tokens=len(state.output))
                logits[row].fill_(-float('inf'))
                logits[row, token] = 0
        return logits


class AuditScheduler(Scheduler):
    """Read-only tracing around the stock scheduler; all decisions delegated."""
    def schedule(self):
        before = {key: req.num_computed_tokens for key, req in self.requests.items()}
        result = super().schedule()
        active = []
        for key in result.num_scheduled_tokens:
            req = self.requests[key]
            active.append(dict(key=key, computed_before=before.get(key, 0),
                               computed_after=req.num_computed_tokens,
                               output_tokens=len(req.output_token_ids),
                               preemptions=req.num_preemptions,
                               blocks=self.kv_cache_manager.get_block_ids(key)))
        emit('scheduler', 'step', active=active,
             new=[r.req_id for r in result.scheduled_new_reqs],
             finished=sorted(result.finished_req_ids),
             waiting=[r.request_id for r in self.waiting])
        return result
