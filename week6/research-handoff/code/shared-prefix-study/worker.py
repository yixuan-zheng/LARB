"""Pinned vLLM worker control with global token offsets across suffix calls."""
import json
import os
import time
from pathlib import Path

from vllm.v1.sample.logits_processor.interface import LogitsProcessor, MoveDirectionality
from control import RequestControl, move_rows

ROOT = Path(os.environ['PREFIX_OUT'])


from protocol import JoinedTokens, synthetic_token


def emit(event, **data):
    with (ROOT / 'worker.jsonl').open('a') as handle:
        handle.write(json.dumps(dict(event=event, monotonic=time.monotonic(), **data))+'\n')


class PrefixProcessor(LogitsProcessor):
    def __init__(self, vllm_config, device, is_pin_memory):
        assert vllm_config.model_config.logprobs_mode == 'raw_logprobs'
        self.rows = {}
        self.synthetic = {}
        # A controlled worker-side test verifies the numerical raw-logprob path.
        import torch
        from vllm.v1.sample.sampler import Sampler
        logits = torch.tensor([[0., 1., 2.]], device=device)
        actual = Sampler.compute_logprobs(logits)
        expected = torch.log_softmax(logits.float(), dim=-1)
        assert torch.allclose(actual, expected, atol=1e-6)
        assert not torch.allclose(actual, torch.log_softmax(logits / 0.6, dim=-1))
        emit('logprob_numeric_gate', passed=True, actual=actual.cpu().tolist())
        emit('initialized')

    def is_argmax_invariant(self):
        return False

    def update_state(self, batch_update):
        if batch_update is None:
            return
        for row in batch_update.removed:
            self.rows.pop(row, None)
            self.synthetic.pop(row, None)
        for row, params, prompt, output in batch_update.added:
            data = dict(params.extra_args['prefix_control'])
            prefix = data.pop('prefix')
            synthetic = data.pop('synthetic', None)
            assert list(prompt[-len(prefix):]) == prefix if prefix else True
            state = RequestControl(output=JoinedTokens(prefix, output), **data)
            self.rows[row] = state
            self.synthetic[row] = synthetic
            emit('admitted', key=state.key, prefix_tokens=len(prefix), budget=state.budget)
        moves = [(a, b, d == MoveDirectionality.SWAP) for a, b, d in batch_update.moved]
        move_rows(self.rows, moves)
        move_rows(self.synthetic, moves)

    def apply(self, logits):
        for row, state in self.rows.items():
            before = state.force_start
            token = state.next_forced()
            synthetic = self.synthetic.get(row)
            fixture_token = synthetic_token(synthetic, len(state.output))
            if fixture_token is not None:
                token = fixture_token
            if before is None and state.force_start is not None:
                emit('cue_started', key=state.key, global_position=state.force_start)
            if token is not None:
                logits[row].fill_(-float('inf'))
                logits[row, token] = 0
        return logits
