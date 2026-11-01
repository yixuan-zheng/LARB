"""Pinned vLLM 0.11.2 queue telemetry and logits-only budget control."""
import json
import os
from pathlib import Path
import time

from vllm.v1.sample.logits_processor.interface import LogitsProcessor, MoveDirectionality
from vllm.v1.core.sched.scheduler import Scheduler
from control import RequestControl, move_rows
from policy import apply_pressure, forced_token

ROOT = Path(os.environ['BURST_OUT'])


def emit(stream, event, **data):
    with (ROOT / (stream + '.jsonl')).open('a') as handle:
        handle.write(json.dumps(dict(event=event, monotonic=time.monotonic(),
                                    pid=os.getpid(), **data)) + '\n')


def atomic(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value))
    temp.replace(path)


def read_pressure():
    return json.loads((ROOT / 'pressure.json').read_text())


class BurstProcessor(LogitsProcessor):
    def __init__(self, vllm_config, device, is_pin_memory):
        self.rows = {}
        self.policies = {}
        self.caps = set()
        emit('worker', 'initialized')

    def is_argmax_invariant(self):
        return False

    def update_state(self, batch_update):
        if batch_update:
            for row in batch_update.removed:
                self.rows.pop(row, None)
            for row, params, prompt, output in batch_update.added:
                data = dict(params.extra_args['burst'])
                mode = data.pop('policy')
                state = RequestControl(output=output, **data)
                self.rows[row] = state
                self.policies[state.key] = mode
                emit('worker', 'admitted', key=state.key, row=row,
                     initial_budget=state.budget, output_object=id(output))
            for a, b, direction in batch_update.moved:
                emit('worker', 'row_move', source=a, target=b, direction=direction.name)
            move_rows(self.rows, [(a, b, d == MoveDirectionality.SWAP)
                                 for a, b, d in batch_update.moved])
        snapshot = read_pressure()
        for row, state in self.rows.items():
            old_close = state.close_index
            state.refresh()
            if old_close is None and state.close_index is not None:
                emit('worker', 'thinking_closed', key=state.key,
                     close_index=state.close_index, forced=state.force_start is not None)
            phase = state.key.rsplit('-', 1)[0]
            waiting = [k for k in snapshot['waiting'] if k.startswith(phase + '-')]
            if apply_pressure(state, self.policies[state.key], len(waiting)):
                emit('worker', 'live_reduction', key=state.key, row=row,
                     tokens=len(state.output), budget=state.budget,
                     waiting=waiting, pressure_step=snapshot['step'],
                     pressure_age_ms=1000*(time.monotonic()-snapshot['monotonic']),
                     output_object=id(state.output))

    def apply(self, logits):
        for row, state in self.rows.items():
            before = state.force_start
            token, reason = forced_token(state)
            if before is None and state.force_start is not None:
                emit('worker', 'cue_started', key=state.key, tokens=len(state.output),
                     budget=state.budget, output_object=id(state.output))
            if reason and state.key not in self.caps:
                self.caps.add(state.key)
                emit('worker', reason, key=state.key, tokens=len(state.output))
            if token is not None:
                logits[row].fill_(-float('inf'))
                logits[row, token] = 0
        return logits


def request_key(req):
    return req.sampling_params.extra_args['burst']['key']


class QueueAuditScheduler(Scheduler):
    """Observe the stock scheduler; do not change admission or batching decisions."""
    def schedule(self):
        before = {key: r.num_computed_tokens for key, r in self.requests.items()}
        result = super().schedule()
        self.audit_step = getattr(self, 'audit_step', 0) + 1
        active = []
        for key in result.num_scheduled_tokens:
            req = self.requests[key]
            row = dict(key=request_key(req), computed_before=before.get(key, 0),
                       computed_after=req.num_computed_tokens,
                       preemptions=req.num_preemptions)
            if self.audit_step % 128 == 0 or result.scheduled_new_reqs or result.finished_req_ids:
                row['blocks'] = self.kv_cache_manager.get_block_ids(key)
            active.append(row)
        waiting = [request_key(req) for req in self.waiting]
        snapshot = dict(step=self.audit_step, monotonic=time.monotonic(),
                        active=[r['key'] for r in active], waiting=waiting)
        atomic(ROOT / 'pressure.json', snapshot)
        emit('scheduler', 'step', step=self.audit_step, active=active, waiting=waiting,
             new=[r.req_id for r in result.scheduled_new_reqs],
             finished=sorted(result.finished_req_ids))
        return result
