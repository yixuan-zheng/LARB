"""Bounded paired decode-width screening; no quality or serving claims."""
import argparse
import gc
import hashlib
import json
import random
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'code'))
import torch
import torch.nn.functional as F
import build_worker
import latency_lib as lib


def sliced_forward(mlp, x):
    w = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:w])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(x, mlp.up_proj.weight[:w])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :w])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    lib.add_common_args(p, default_reps=40, default_warmup=8)
    p.add_argument('--batches', default='1,8,16,32,64')
    p.add_argument('--contexts', default='128,2048')
    p.add_argument('--prefill-chunk', type=int, default=256)
    a = p.parse_args()
    lib.prepare_runtime(a)
    out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
    data = dict(manifest=lib.base_manifest(a, 'decode_rescue'), completed=False,
                protocol=dict(paired_shuffled=True, seed=a.seed, reps=a.reps,
                              warmup=a.warmup, prefill_chunk=a.prefill_chunk,
                              constant_context=True, cache_history='same width as decode',
                              timing='single decode step, prefill and width application excluded',
                              implementation='one resident text-only Large worker, dynamic FFN slices',
                              screening_threshold_percent=10, quality_evaluated=False), cells=[])
    def save():
        tmp = out.with_suffix('.tmp'); tmp.write_text(json.dumps(data, indent=2)+'\n'); tmp.replace(out)
    data['clock_ramp'] = lib.clock_ramp(a.clock_ramp_s)
    data['clock_guard'] = lib.wait_for_sm_clock(a.min_sm_clock_mhz)
    save()
    if a.strict_clock and not data['clock_guard'].get('ok'):
        raise RuntimeError('GPU clock guard failed')
    model, tok, info = build_worker.build_worker('large', lib.dtype_of(a))
    data['worker'] = info
    layers = model.model.layers
    def select(name):
        for layer, width in zip(layers, lib.preset_widths(name)):
            layer.mlp.active_width = width
    with torch.inference_mode():
        probe = tok('The capital of France is', return_tensors='pt')['input_ids'].cuda()
        reference = model(input_ids=probe, use_cache=False, logits_to_keep=1).logits.clone()
        for layer in layers:
            layer.mlp.forward = types.MethodType(sliced_forward, layer.mlp)
        select('large')
        actual = model(input_ids=probe, use_cache=False, logits_to_keep=1).logits
        data['large_patch_max_logit_difference'] = (reference-actual).abs().max().item()
        assert data['large_patch_max_logit_difference'] == 0
        del reference, actual, probe
    harness = lib.Harness(a)
    continuation = lib.next_token_id(tok).cuda()
    for context in map(int, a.contexts.split(',')):
        prompt, digest = lib.build_prompt_ids(tok, context)
        prompt = prompt.cuda()
        for batch in map(int, a.batches.split(',')):
            cell = dict(batch=batch, context=context, prompt_sha256=digest, completed=False)
            data['cells'].append(cell); save()
            print(f'CELL B{batch} L{context}', flush=True)
            def measure():
                ids = prompt.repeat(batch, 1).contiguous()
                next_ids = continuation.repeat(batch, 1)
                def prepare(cfg):
                    select(cfg['key'])
                    cache = None
                    for offset in range(0, context, a.prefill_chunk):
                        r = model(input_ids=ids[:, offset:offset+a.prefill_chunk],
                                  past_key_values=cache, use_cache=True, logits_to_keep=1)
                        cache = r.past_key_values
                        del r
                    return cache
                def step(cfg, cache):
                    return model(input_ids=next_ids, past_key_values=cache,
                                 use_cache=True, logits_to_keep=1)
                with torch.inference_mode():
                    samples = harness.sweep([dict(key='large'), dict(key='small')],
                                            prepare, step, a.warmup, a.reps)
                return samples
            try:
                torch.cuda.reset_peak_memory_stats()
                samples = measure()
                cell.update(completed=True, samples=samples, summary=lib.summarize_samples(samples),
                            comparisons={m:lib.compare_pairs(samples, 'large', 'small', metric=m, seed=a.seed)
                                         for m in ('wall_ms', 'gpu_ms')},
                            peak_allocated_bytes=torch.cuda.max_memory_allocated())
                v = cell['comparisons']['wall_ms']
                print(f"RESULT B{batch} L{context} speedup={v['speedup']:.4f} ratioCI={v['ratio_lo']:.4f},{v['ratio_hi']:.4f}", flush=True)
            except torch.OutOfMemoryError:
                cell.update(status='OOM', reason='allocation failed during preparation or decode')
                print(f'OOM B{batch} L{context}', flush=True)
            gc.collect(); torch.cuda.empty_cache(); save()
    data['completed'] = True
    data['clocks_at_end'] = lib.clocks_snapshot()
    data['script_sha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    save()
    print('BENCHMARK COMPLETE', flush=True)


if __name__ == '__main__':
    main()
