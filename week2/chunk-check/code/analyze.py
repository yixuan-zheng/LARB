"""Audit raw serving runs and report uncorrected, latency-only comparisons."""
import argparse
import csv
import gzip
import json
from pathlib import Path
import statistics

COMPARISONS = [('hybrid_original', 'large_original'),
               ('large_chunk512', 'large_original'),
               ('hybrid_chunk512', 'large_chunk512')]

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('raw')
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    opener = gzip.open if args.raw.endswith('.gz') else open
    with opener(args.raw, 'rt') as fh:
        data = json.load(fh)
    assert data['completed'], 'Do not present an unfinished experiment as complete'
    assert data['gates']['passed'] and all(g['passed'] for g in data['chunk_gates'])
    assert len(data['runs']) == 12
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    runs, index = [], {}
    for r in data['runs']:
        report = r['report']
        assert r['accounting']['passed'], r['accounting']
        assert r['mode'] == 'measured' and not r['policy_stub']
        assert report['requests'] == report['completed'] == len(r['requests']) == 150
        assert not report['rejected'] and not r['quality_validated']
        assert len(r['generated_tokens']) == 150
        for req in r['requests']:
            assert req['finished']
            assert len(r['generated_tokens'][req['request_id']]) == req['output_tokens']
            actual_pass = req['ttft_s'] <= 1 and (req['max_itl_s'] is None or req['max_itl_s'] <= .2)
            assert actual_pass == req['primary_pass']
        assert abs(sum(q['primary_pass'] for q in r['requests'])/150-report['attainment']) < 1e-12
        assert sum(q['prompt_tokens'] for q in r['requests']) == sum(i['prefill_tokens'] for i in r['iterations'])
        assert all(i['mode'] == 'measured' for i in r['iterations'])
        row = {'configuration': r['configuration'], 'rep': r['rep'],
          'attainment': report['attainment'], 'on_time_requests_per_s': report['goodput_eval_window'],
          'throughput_rps': report['throughput_rps_trace_window'],
          'ttft_p50_ms': report['ttft_s']['median'], 'ttft_p99_ms': report['ttft_s']['p99'],
          'max_itl_p50_ms': report['max_itl_s']['median'], 'max_itl_p95_ms': report['max_itl_s']['p95'],
          'max_itl_p99_ms': report['max_itl_s']['p99'],
          'slow_iterations_over200ms': sum(i['t_end_s']-i['t_start_s'] > .2 for i in r['iterations']),
          'iterations_over400ms': sum(i['t_end_s']-i['t_start_s'] > .4 for i in r['iterations']),
          'worst_iteration_ms': max(1000*(i['t_end_s']-i['t_start_s']) for i in r['iterations']),
          'fail_ttft': report['breakdown']['fail_ttft'], 'fail_itl': report['breakdown']['fail_itl'],
          'fail_both': report['breakdown']['fail_ttft+itl'], 'wall_s': report['wall_s'],
          'cache_rebuild_ms': r['report']['cache_rebuild_ms_total'],
          'switches': report['switches_applied']}
        runs.append(row)
        key = (r['configuration'], r['rep'])
        assert key not in index
        index[key] = r
    paired = []
    for a, b in COMPARISONS:
        for rep in range(3):
            ra, rb = index[a, rep], index[b, rep]
            qa = {r['request_id']: r for r in ra['requests']}
            qb = {r['request_id']: r for r in rb['requests']}
            assert qa.keys() == qb.keys()
            for rid in qa:
                for k in ('prompt_tokens', 'output_tokens'):
                    assert qa[rid][k] == qb[rid][k]
            paired.append({'candidate': a, 'reference': b, 'rep': rep,
                'attainment_delta_pp': 100*(ra['report']['attainment']-rb['report']['attainment']),
                'candidate_only_pass': sum(qa[k]['primary_pass'] and not qb[k]['primary_pass'] for k in qa),
                'reference_only_pass': sum(qb[k]['primary_pass'] and not qa[k]['primary_pass'] for k in qa),
                'changed_token_sequences': sum(ra['generated_tokens'][k] != rb['generated_tokens'][k] for k in qa),
                'on_time_rps_delta': ra['report']['goodput_eval_window']-rb['report']['goodput_eval_window'],
                'throughput_change_pct': 100*(ra['report']['throughput_rps_trace_window']/rb['report']['throughput_rps_trace_window']-1)})
    for name, rows in [('runs.csv', runs), ('paired.csv', paired)]:
        with (out/name).open('w', newline='') as fh:
            writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    configs = [c['name'] for c in data['protocol']['configs']]
    text = ['# Final prefill chunk comparison', '',
        'Three repetitions per configuration, 150 identical trace requests per run,',
        'rate scale 0.1; TTFT <= 1 s and max token gap <= 200 ms. All stalls retained.',
        'All figures are latency-only; answer quality is not evaluated.', '',
        '| Configuration | Attainment per run | Mean attainment | Mean on-time req/s | Mean throughput req/s | TTFT p50, ms |',
        '|---|---|---:|---:|---:|---:|']
    for cfg in configs:
        rows = [r for r in runs if r['configuration'] == cfg]
        text.append(f"| {cfg} | " + ', '.join(f"{100*r['attainment']:.1f}%" for r in rows) +
           f" | {100*statistics.mean(r['attainment'] for r in rows):.1f}% | " +
           f"{statistics.mean(r['on_time_requests_per_s'] for r in rows):.3f} | " +
           f"{statistics.mean(r['throughput_rps'] for r in rows):.3f} | " +
           f"{statistics.mean(r['ttft_p50_ms'] for r in rows):.1f} |")
    text += ['', '| Comparison | Attainment difference per repetition |', '|---|---|']
    for a,b in COMPARISONS:
        rows = [r for r in paired if r['candidate']==a and r['reference']==b]
        text.append(f"| {a} minus {b} | " + ', '.join(f"{r['attainment_delta_pp']:+.1f} pp" for r in rows) + ' |')
    text += ['', 'These within-allocation repetitions do not establish across-day uncertainty.',
      'Token differences are diagnostics, not scored quality failures. Chunking may change',
      'BF16 numerical paths and therefore generated answers. This remains one model, one',
      'GPU, one low-load trace and the padded-cache eager harness. Raw request and',
      'iteration records are retained; 0.4-second stalls are counted, never removed.', '']
    (out/'RESULTS.md').write_text('\n'.join(text))
    (out/'audit.json').write_text(json.dumps({'passed': True, 'runs': 12,
          'requests_per_run': 150, 'gates_passed': True, 'stalls_retained': True,
          'quality_evaluated': False, 'upstream_commit': data['protocol']['upstream_commit']}, indent=2)+'\n')
    print('\n'.join(text))

if __name__ == '__main__':
    main()
