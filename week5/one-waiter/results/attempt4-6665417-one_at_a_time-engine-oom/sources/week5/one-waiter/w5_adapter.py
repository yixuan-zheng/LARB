"""Pinned vLLM 0.11.2 integration for Week 5; stock scheduling plus logits."""
import time
import bootstrap  # noqa: F401

from vllm.v1.sample.logits_processor.interface import MoveDirectionality
from adapter import (BurstProcessor, QueueAuditScheduler, emit, read_pressure)
from w5_policy import attach_admission, make_control, move_rows, reduce_live


class AdmissionScheduler(QueueAuditScheduler):
    def schedule(self):
        result = super().schedule()  # Includes stock schedule and its exact snapshot.
        snapshot = read_pressure()
        if snapshot['step'] != self.audit_step:
            raise RuntimeError('Admission snapshot does not match this scheduling step')
        for request in result.scheduled_new_reqs:
            data = request.sampling_params.extra_args['burst']
            if attach_admission(data, snapshot):
                emit('scheduler', 'admission_decision', key=data['key'],
                     policy=data['policy'], **data['admission'])
        return result


class AdmissionProcessor(BurstProcessor):
    """Reuse the proven token-forcing path; replace initialization and updates."""
    def __init__(self, vllm_config, device, is_pin_memory):
        super().__init__(vllm_config, device, is_pin_memory)
        self.by_key = {}
        self.first_progress = set()

    def update_state(self, batch_update):
        if batch_update:
            for row in batch_update.removed:
                self.rows.pop(row, None)
            for row, params, prompt, output in batch_update.added:
                data = params.extra_args['burst']
                key = data['key']
                if key in self.by_key:
                    state = self.by_key[key]
                    if list(state.output) != list(output):
                        raise RuntimeError('Resumed output differs from retained request state')
                    state.output = output
                    emit('worker', 'resumed', key=key, row=row, budget=state.budget)
                else:
                    state = make_control(data, output)
                    self.by_key[key] = state
                    self.policies[key] = data['policy']
                    emit('worker', 'admitted', key=key, policy=data['policy'], row=row,
                         initial_budget=state.budget, tokens=len(output),
                         admission_step=data['admission']['step'],
                         trigger=data['admission']['trigger'],
                         waiting=data['admission']['waiting'], output_object=id(output))
                self.rows[row] = state
            for a, b, direction in batch_update.moved:
                emit('worker', 'row_move', source=a, target=b, direction=direction.name)
            move_rows(self.rows, [(a, b, d == MoveDirectionality.SWAP)
                                 for a, b, d in batch_update.moved])
        snapshot = read_pressure()
        for row, state in self.rows.items():
            if state.output and state.key not in self.first_progress:
                self.first_progress.add(state.key)
                emit('worker', 'generation_observed', key=state.key,
                     tokens=len(state.output), budget=state.budget)
            old_close = state.close_index
            state.refresh()
            if old_close is None and state.close_index is not None:
                emit('worker', 'thinking_closed', key=state.key,
                     close_index=state.close_index, forced=state.force_start is not None)
            phase = state.key.rsplit('-', 1)[0]
            waiting = [key for key in snapshot['waiting'] if key.startswith(phase + '-')]
            previous = state.budget
            if reduce_live(state, self.policies[state.key], len(waiting)):
                emit('worker', 'live_reduction', key=state.key, row=row,
                     tokens=len(state.output), previous_budget=previous, budget=state.budget,
                     version=state.version, waiting=waiting, pressure_step=snapshot['step'],
                     pressure_age_ms=1000 * (time.monotonic() - snapshot['monotonic']),
                     output_object=id(state.output))
