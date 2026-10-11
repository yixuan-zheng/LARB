"""Final bounded comparison using upstream mixed-serving without modifying it."""
import argparse
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time

REPO = Path(__file__).resolve().parents[3]
UPSTREAM = REPO / 'week2/mixed-serving'
sys.path.insert(0, str(UPSTREAM / 'code'))
sys.path.insert(0, str(REPO / 'week1/latency-baselines'))
import serving_core as core
import serving_lib as serving
import run_serving as runner
import validate_harness as gates
import policies
import workload
import slo
import latency_lib as lib
import torch

def save(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=1, default=str) + '\n')
    temporary.replace(path)

def correctness(executor, config, policy):
    """Check heterogeneous batched tokens against per-row execution, including long contexts."""
    trace = gates.smoke_trace(prompt_lengths=(700, 2300), output_tokens=8, spacing_s=0,
                             request_prefix='chunkgate')
    observed = {}
    checks = []
    for mode in ('batched', 'single_row'):
        clone = gates._fresh(executor, config, decode_mode=mode)
        state, _ = serving.measured_run(trace, config, policies.build_policy(policy),
                         slo.SLOContract(ttft_s=1e9, itl_gate_s=1e9), clone)
        checks.append(core.accounting_check(state)['passed'])
        observed[mode] = dict(clone.retired_tokens)
    passed = all(checks) and len(observed['batched']) == 2 and observed['batched'] == observed['single_row']
    return {'gate': 'long_context_tokens_batched_equal_per_row', 'policy': policy,
            'prefill_chunk': config.prefill_chunk, 'passed': passed, 'tokens': observed}

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    out = Path(args.out)
    common = core.EngineConfig(max_running=48)
    configs = [
        ('large_original', 'static_large', common),
        ('hybrid_original', 'phase_hybrid', common),
        ('large_chunk512', 'static_large', dataclasses.replace(common, prefill_chunk=512)),
        ('hybrid_chunk512', 'phase_hybrid', dataclasses.replace(common, prefill_chunk=512)),
    ]
    trace_path = UPSTREAM / 'traces/azure_conv_steady.json'
    trace = workload.load_trace(trace_path, rate_scale=0.1, limit=150)
    contract = runner.build_contract(runner.build_parser().parse_args(['--trace', str(trace_path)]))
    ns = argparse.ArgumentParser(add_help=False)
    lib.add_common_args(ns, default_reps=1, default_warmup=1)
    lib.prepare_runtime(ns.parse_args([]))
    data = {'started_utc': runner.utc_now(), 'completed': False, 'runs': [],
        'protocol': {'upstream_commit': '96e8f1097d2f0be6a513eede6cda04330824da71',
          'trace': 'azure_conv_steady', 'trace_sha256': hashlib.sha256(trace_path.read_bytes()).hexdigest(),
          'requests': 150, 'rate_scale': 0.1, 'repetitions': 3,
          'configs': [{'name': name, 'policy': policy, 'config': cfg.to_dict()} for name, policy, cfg in configs],
          'order': 'rotate four configurations by repetition; no outcome-dependent tuning',
          'quality_evaluated': False, 'metrics_are_latency_only': True, 'stalls_retained': True},
        'environment': {'python': sys.version, 'torch': torch.__version__, 'host': platform.node(),
          'slurm_job_id': os.environ.get('SLURM_JOB_ID'), 'device': torch.cuda.get_device_name(),
          'model': lib.MODEL, 'revision': lib.REVISION},
        'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'upstream_source_sha256': {str(p.relative_to(REPO)): hashlib.sha256(p.read_bytes()).hexdigest()
             for folder in (UPSTREAM/'code', REPO/'week1/latency-baselines')
             for p in folder.glob('*.py')}}
    save(out, data)
    lib.clock_ramp(2.0)
    clock = lib.wait_for_sm_clock(1500)
    data['clock_guard'] = clock
    if not clock['ok']:
        raise RuntimeError('GPU clock guard did not pass')
    executor, statics, _, infos = serving.build_executor(common, statics=('small',),
                                      slice_mode='materialize', device='cuda')
    data['workers'] = infos
    data['gates'] = gates.run_gates(executor, statics, trace=gates.smoke_trace(),
                         config=common, contract=contract, level='full')
    data['chunk_gates'] = [correctness(executor, cfg, policy) for name, policy, cfg in configs]
    save(out, data)
    if not data['gates']['passed'] or not all(g['passed'] for g in data['chunk_gates']):
        raise RuntimeError('Correctness gates failed; no timing comparison authorized by protocol')
    print('GATES PASSED', flush=True)
    # Warm each configuration outside measured runs; retire its caches before timing.
    for _, policy, cfg in configs:
        serving.measured_run(gates.smoke_trace(prompt_lengths=(700, 2300), output_tokens=8),
                             cfg, policies.build_policy(policy), contract, executor)
    for rep in range(3):
        for name, policy, cfg in configs[rep:] + configs[:rep]:
            assert not executor.rows and not executor.states
            executor.retired_tokens = {}
            executor.cache_rebuild_ms_total = 0.0
            executor.kv_high_water = 0
            torch.cuda.synchronize()
            started = time.monotonic()
            print('START', name, rep, flush=True)
            entry = runner.run_one({'policy': policy, 'rep': rep}, trace, cfg, contract,
                                   mode='measured', executor=executor, progress=1000)
            entry['configuration'] = name
            entry['elapsed_s'] = time.monotonic() - started
            entry['quality_validated'] = False
            entry['generated_tokens'] = dict(executor.retired_tokens)
            data['runs'].append(entry)
            save(out, data)
            summary = runner.summary_row(entry)
            summary['configuration'] = name
            print('RESULT', json.dumps(summary), flush=True)
            if not entry['accounting']['passed'] or entry['report']['completed'] != 150 or entry['report']['rejected']:
                raise RuntimeError('Per-run accounting failed')
    data['completed'] = True
    data['finished_utc'] = runner.utc_now()
    save(out, data)
    print('FINAL COMPARISON COMPLETE', flush=True)

if __name__ == '__main__':
    main()
