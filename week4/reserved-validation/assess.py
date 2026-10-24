"""Reproduce 5C descriptive diagnostics from the six immutable graded runs."""
from collections import Counter
import hashlib
import gzip
import json
from pathlib import Path
import math
import statistics

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def assess():
    ledger = json.loads((HERE / 'campaign.json').read_text())
    roots = [HERE / 'results' / ('job-' + j['job']) for j in ledger['jobs']]
    summaries = [json.loads((p / 'analysis/summary.json').read_text()) for p in roots]
    assert len(summaries) == 6 and all(s['validation_passed'] for s in summaries)
    rows = [r for p in roots for r in json.loads((p / 'analysis/graded.json').read_text())]
    assert len(rows) == 288
    conditions = ['low_load', 'late_burst', 'sustained_pressure']
    pairs = []
    quality_cases = []
    for root, summary in zip(roots, summaries):
        for pair in summary['paired']:
            row = dict(condition=summary['condition'], shard=summary['shard'], **pair)
            pairs.append(row)
            if pair['correctness_delta']:
                quality_cases.append(dict(**row, raw_records=[
                    str((root / 'requests' / (pair[p + '_key'] + '.json')).relative_to(REPO))
                    for p in ['admission', 'live']]))
    comparisons = []
    performance = []
    for condition in conditions:
        group = [p for p in pairs if p['condition'] == condition]
        comparisons.append(dict(condition=condition, pairs=len(group),
            deadline_gains=sum(p['deadline_delta'] > 0 for p in group),
            deadline_losses=sum(p['deadline_delta'] < 0 for p in group),
            eventual_gains=sum(p['correctness_delta'] > 0 for p in group),
            eventual_losses=sum(p['correctness_delta'] < 0 for p in group)))
        for policy in ['admission', 'live']:
            group = [r for r in rows if (r['condition'], r['policy']) == (condition, policy)]
            latencies = sorted(r['client_completion_seconds'] for r in group)
            performance.append(dict(condition=condition, policy=policy, n=len(group),
                median_client_seconds=statistics.median(latencies),
                p95_client_seconds=latencies[math.ceil(.95 * len(group)) - 1],
                mean_queue_seconds=statistics.mean(r['queue_seconds'] for r in group),
                thinking_tokens=sum(r['thinking_tokens'] for r in group),
                cue_tokens=sum(r['cue_tokens'] for r in group),
                answer_tokens=sum(r['answer_tokens'] for r in group),
                output_tokens=sum(r['output_tokens'] for r in group),
                live_reductions=sum(r['live_reduction'] for r in group),
                binding_live_cutoffs=sum(r['binding_live_cutoff'] for r in group),
                failures=dict(Counter(r['finish'] for r in group if r['finish'] != 'normal'))))
    resource_rows = []
    for root in roots:
        fields = (root / 'accounting.txt').read_text().strip().split('|')
        assert fields[1] == 'COMPLETED' and fields[3] == '0:0'
        assert 'gres/gpu=1' in fields[4]
        hardware = (root / 'hardware.txt').read_text().splitlines()[1:]
        assert hardware and all('NVIDIA H100 80GB HBM3' in row for row in hardware)
        archive = json.loads((root / 'storage-manifest.json').read_text())['scheduler.jsonl']
        assert hashlib.sha256((root / 'scheduler.jsonl.gz').read_bytes()).hexdigest() == archive['gzip_sha256']
        raw_hash = hashlib.sha256()
        with gzip.open(root / 'scheduler.jsonl.gz', 'rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                raw_hash.update(chunk)
        assert raw_hash.hexdigest() == archive['raw_sha256']
        resource_rows.append(dict(job=fields[0], gpu_seconds=int(fields[2]),
                                  start=fields[5], end=fields[6], hardware=sorted(set(hardware))))
    selected = sorted({r['index'] for r in rows})
    assert len(selected) == 24 and min(selected) >= 100
    exposed = sorted(set(range(100)) | set(selected))
    result = dict(measured_outcomes=len(rows), calibration_requests=12,
        raw_requests=sum(len(list((p / 'requests').glob('*.json'))) for p in roots),
        unique_questions=len(selected), parser_issues=sum(bool(r['grading']['issue']) for r in rows),
        paired_comparisons=comparisons, performance=performance, quality_change_cases=quality_cases,
        paired_initial_budget_matches=sum(p['initial_budget_match'] for p in pairs),
        paired_initial_budget_total=len(pairs), resource_rows=resource_rows,
        allocated_gpu_seconds=sum(r['gpu_seconds'] for r in resource_rows),
        overhead_limit='Cue/output token costs and end-to-end latency are recorded. Isolated controller CPU time and instrumentation overhead were not measured.',
        grading_metrics_source=dict(path='week4/step1/controlled-comparison/metrics.py',
            sha256=hashlib.sha256((REPO / 'week4/step1/controlled-comparison/metrics.py').read_bytes()).hexdigest()),
        exposure=dict(initial_recorded_indices=list(range(100)), newly_exposed_indices=selected,
            recorded_exposed_count=len(exposed), provisionally_remaining_indices=sorted(set(range(500)) - set(exposed)),
            limitation='Recorded project exposure only; external/unrecorded use and pretraining remain unknown.'))
    assert result['raw_requests'] == 300
    output = HERE / 'analysis/assessment.json'
    output.write_text(json.dumps(result, indent=2) + '\n')
    print('5C diagnostics saved:', output.relative_to(REPO))


if __name__ == '__main__':
    assess()
