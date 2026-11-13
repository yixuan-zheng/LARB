"""Forward replay on the pinned BF16 model, with upstream parity before bulk."""
import argparse
import hashlib
import importlib.metadata
import json
import math
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
from transformers import AutoModelForCausalLM, AutoTokenizer

from prepare import read, token_hash
from upstream_features import get_prefix_hidden_states

HERE = Path(__file__).resolve().parent


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def write(path, obj):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(obj, indent=2)+'\n')
    tmp.replace(path)


class ExactTokenizer:
    def __init__(self, tokenizer, prompt):
        self.tokenizer, self.prompt = tokenizer, prompt

    def __call__(self, *_args, **_kwargs):
        return SimpleNamespace(input_ids=torch.tensor([self.prompt]))

    def decode(self, *args, **kwargs):
        return self.tokenizer.decode(*args, **kwargs)


class FinalLogitsOnly:
    def __init__(self, model):
        self.model, self.device = model, model.device

    def __call__(self, **kwargs):
        return self.model(logits_to_keep=1, **kwargs)


@torch.inference_mode()
def direct(model, tokenizer, row, checkpoints, config=None):
    ids = row['prompt'] + row['prefix']
    assert token_hash(ids) == row['input_hash']
    checks = []
    features = []
    elapsed = {}
    for t in checkpoints:
        start = time.monotonic()
        ref = get_prefix_hidden_states(FinalLogitsOnly(model), ExactTokenizer(tokenizer, row['prompt']),
                                       '', torch.tensor(row['prefix'][:t], dtype=torch.long), [t], t)[t]
        feature = ref['h_t']
        assert feature.shape == (model.config.hidden_size,)
        assert np.isfinite(feature).all() and np.linalg.norm(feature) > 0
        features.append(feature)
        elapsed[t] = time.monotonic() - start
        if config is not None or t == 4096:
            inputs = torch.tensor([row['prompt'] + row['prefix'][:t]], device=model.device)
            hidden = model.model(input_ids=inputs, attention_mask=torch.ones_like(inputs),
                                 use_cache=False).last_hidden_state[0]
            assert hidden.shape == (inputs.shape[1], model.config.hidden_size)
            last = hidden[-1].float().cpu().numpy()
            if config is not None:
                expected = hidden[-4:].mean(dim=0).float().cpu().numpy() if t else last
                error = float(np.linalg.norm(expected-feature)/np.linalg.norm(feature))
                cosine = float(expected@feature/(np.linalg.norm(expected)*np.linalg.norm(feature)))
                checks.append(dict(key=row['key'], checkpoint=t, relative_l2=error, cosine=cosine))
            if t == 4096:
                assert np.isfinite(last).all() and np.linalg.norm(last) > 0
                features.append(last)
                elapsed[t] = time.monotonic() - start
    return np.stack(features), elapsed, checks


def run(model_path, out):
    args_deadline = time.monotonic() + 3400
    out.mkdir(parents=True, exist_ok=False)
    gate = dict(passed=False, checks=[])
    try:
        lock = HERE/'release-lock.json'
        for name, expected in read(lock).items():
            assert digest(HERE/name) == expected, name
        config = read(HERE/'config.json')
        rows = read(HERE/'inputs.json')
        assert len(rows) == len({row['key'] for row in rows}) == 115
        for package in ('torch','transformers'):
            assert importlib.metadata.version(package).split('+')[0] == config[package]
        manifest = read(HERE/'model-files.json')
        assert model_path.name == manifest['revision'] == config['revision']
        for name, info in manifest['files'].items():
            path = model_path/name
            assert path.stat().st_size == info['size'], name
            if 'sha256' in info:
                assert digest(path) == info['sha256'], name
            else:
                blob = path.read_bytes()
                assert hashlib.sha1(f'blob {len(blob)}\0'.encode()+blob).hexdigest() == info['git_blob'], name
        assert torch.cuda.device_count() == 1 and 'L40S' in torch.cuda.get_device_name()
        torch.cuda.reset_peak_memory_stats()
        free, total = torch.cuda.mem_get_info()
        write(out/'manifest.json', dict(config=config, release_sha256=digest(lock),
                                       gpu=torch.cuda.get_device_name(), free_bytes=free, total_bytes=total))
        model = AutoModelForCausalLM.from_pretrained(model_path, local_files_only=True,
                                                   dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda').eval()
        assert model.dtype == torch.bfloat16
        tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
        close = tokenizer.convert_tokens_to_ids('</think>')
        eos = tokenizer.convert_tokens_to_ids('<|im_end|>')
        assert all(len(row['prefix']) == 4096 and not {close,eos} & set(row['prefix']) for row in rows)
        checkpoints = config['checkpoints']
        by_length = sorted(rows, key=lambda r: (len(r['prompt']),r['key']))
        gate_rows = {}
        timings = []
        core = [0, 4096]
        for row in (by_length[0], by_length[len(rows)//2], by_length[-1]):
            values, elapsed, checks = direct(model, tokenizer, row, checkpoints, config)
            gate_rows[row['key']] = values
            timings.append(elapsed)
            gate['checks'].extend(checks)
            write(out/'engineering-gate.json', gate)
        remaining = len(rows) - len(gate_rows)
        full_seconds = max(sum(t.values()) for t in timings) * remaining
        core_seconds = max(sum(t[i] for i in core) for t in timings) * remaining
        available = min(config['max_projected_seconds'], args_deadline - time.monotonic() - 120)
        gate.update(full_projected_seconds=full_seconds, core_projected_seconds=core_seconds,
                    available_seconds=available, replay_seconds=timings,
                    peak_gib=torch.cuda.max_memory_reserved()/1024**3)
        assert len(gate['checks']) == 36
        assert all(math.isfinite(c['relative_l2']) and c['relative_l2'] <= config['relative_l2_max']
                   and c['cosine'] >= config['cosine_min'] for c in gate['checks']), 'Direct-path parity'
        assert gate['peak_gib'] <= config['max_peak_gib'], 'Peak memory limit'
        selected = checkpoints if full_seconds <= available else core
        assert core_seconds <= available, 'Core replay exceeds available time'
        gate.update(passed=True, checkpoints=selected,
                    scope='full' if selected == checkpoints else 'prompt_and_4k_only')
        write(out/'engineering-gate.json', gate)
    except BaseException as exc:
        gate['failure'] = repr(exc)
        write(out/'engineering-gate.json', gate)
        raise

    columns = [checkpoints.index(t) for t in selected] + [len(checkpoints)]
    features = []
    for row in rows:
        if row['key'] in gate_rows:
            values = gate_rows[row['key']][columns]
        else:
            values, _, _ = direct(model, tokenizer, row, selected)
        features.append(values)
        if len(features)%10 == 0:
            print(f'{len(features)}/{len(rows)} representations',flush=True)
    partial = out/'features.partial.npz'
    np.savez_compressed(partial, X=np.stack(features), keys=[r['key'] for r in rows],
                        checkpoints=selected, questions=[r['question'] for r in rows], hashes=[r['input_hash'] for r in rows])
    partial.replace(out/'features.npz')
    write(out/'status.json',dict(complete=True,rows=len(rows),feature_sha256=digest(out/'features.npz'),
                                  peak_gib=torch.cuda.max_memory_reserved()/1024**3))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('model',type=Path)
    parser.add_argument('out',type=Path)
    args = parser.parse_args()
    run(args.model,args.out)
