"""Join sealed predictions to outcomes and compare ranked cost frontiers."""
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
PRIOR = HERE.parents[1] / 'week6/question-prefix-comparison'
sys.path.insert(0, str(PRIOR))
from evaluate import allocation, auc


def read(path):
    return json.loads(path.read_text())


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    for name, digest in read(HERE / 'freeze.json').items():
        assert file_hash(HERE / name) == digest, name
    forecasts_path = HERE / 'forecasts.jsonl'
    assert file_hash(forecasts_path) == (HERE / 'forecasts.sha256').read_text().strip()
    mapping = read(HERE / 'mapping.json')
    forecasts = {'question': {}, 'bounded': {}}
    seen = set()
    for line in forecasts_path.read_text().splitlines():
        forecast = json.loads(line)
        case_id = forecast['case_id']
        assert case_id not in seen
        seen.add(case_id)
        probabilities = forecast['probabilities']
        assert len(probabilities) == 4 and abs(sum(probabilities) - 1) < 1e-5
        assert all(0 <= probability <= 1 for probability in probabilities)
        assert 1 <= forecast['output_tokens'] <= 96
        identity = mapping[case_id]
        forecasts[identity['condition']][identity['key']] = forecast
    assert seen == set(mapping)
    rows = read(PRIOR / 'joined-predictions.json')
    for row in rows:
        for name, key in [('question', str(row['question_id'])), ('bounded', row['key'])]:
            forecast = forecasts[name][key]
            probability = forecast['probabilities']
            row['net'][name] = probability[1] - probability[2]
            row['probabilities'][name] = probability

    conditions = ['Q', 'question', 'bounded']
    overhead = {'Q': 0}
    usage = {}
    for name, key_field in [('question', 'question_id'), ('bounded', 'key')]:
        calls = [forecasts[name][str(row[key_field])] for row in rows]
        unique = list(forecasts[name].values())
        overhead[name] = sum(r['input_tokens'] + r['output_tokens'] for r in calls)
        usage[name] = {
            'unique_calls': len(unique),
            'costed_calls': len(calls),
            'input_tokens': sum(r['input_tokens'] for r in calls),
            'output_tokens': sum(r['output_tokens'] for r in calls),
            'median_call_seconds': statistics.median(r['seconds'] for r in unique),
            'p95_call_seconds': statistics.quantiles([r['seconds'] for r in unique], n=20, method='inclusive')[18],
            'offline_inference_seconds': sum(r['seconds'] for r in unique),
        }
    grid = {name: [allocation(rows, name, count) for count in range(len(rows) + 1)] for name in conditions}
    target_correct = sum(r['long_correct'] for r in rows)

    def under_budget(name, budget, factor):
        feasible = [r for r in grid[name] if r['expected_tokens'] + factor * overhead[name] <= budget + 1e-9]
        return max(feasible, key=lambda r: (r['expected_correct'], -r['expected_tokens']), default=None)

    def equal_accuracy(name, target):
        feasible = [r for r in grid[name] if r['expected_correct'] >= target - 1e-9]
        return min(feasible, key=lambda r: r['expected_tokens'], default=None)

    sensitivity = []
    for factor in [0, .25, .5, 1, 2]:
        ceiling = grid['Q'][28]['expected_tokens']
        local_ceiling = grid['question'][28]['expected_tokens'] + factor * overhead['question']
        sensitivity.append(dict(
            reader_token_factor=factor,
            archival_ceiling=ceiling,
            local_ceiling=local_ceiling,
            bounded_at_archival_ceiling=under_budget('bounded', ceiling, factor),
            bounded_at_local_ceiling=under_budget('bounded', local_ceiling, factor),
            local_at_archival_ceiling=under_budget('question', ceiling, factor),
        ))

    equal = {name: equal_accuracy(name, target_correct) for name in conditions}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['question_id']].append(row)
    discordant = []
    for question, items in grouped.items():
        if len(items) == 2 and sum(r['gain'] for r in items) == 1:
            gain = next(r for r in items if r['gain'])
            other = next(r for r in items if not r['gain'])
            discordant.append(dict(question=question, gain=gain['key'], other=other['key'],
                                   score_gap=gain['net']['bounded'] - other['net']['bounded']))
    assert len(discordant) == 4
    rng = random.Random(157222)
    differences = {name: [] for name in ['Q', 'question']}
    for _ in range(10000):
        sample = [row for group in rng.choices(list(grouped.values()), k=len(grouped)) for row in group]
        count = len(sample) // 2
        candidate = allocation(sample, 'bounded', count)['expected_correct']
        for name in differences:
            control = allocation(sample, name, count)['expected_correct']
            differences[name].append((candidate - control) / len(sample))
    intervals = {}
    for name, values in differences.items():
        ordered = sorted(values)
        intervals[name] = [ordered[249], ordered[9749]]
    primary = sensitivity[3]['bounded_at_archival_ceiling']
    failures = []
    if primary is None or primary['expected_correct'] < grid['Q'][28]['expected_correct'] + 2 - 1e-9:
        failures.append('Fewer than two additional correct answers at the archival cost ceiling.')
    if equal['bounded']['expected_tokens'] + overhead['bounded'] >= equal['Q']['expected_tokens']:
        failures.append('No charged cost saving at fixed-long accuracy versus archival question-only.')
    if sum(r['score_gap'] > 0 for r in discordant) < 3:
        failures.append('Fewer than three strict gain-seed wins among four discordant questions.')
    break_even = {
        name: (equal[name]['expected_tokens'] - equal['bounded']['expected_tokens']) /
              (overhead['bounded'] - overhead[name])
        for name in ['Q', 'question']
    }
    result = dict(
        population=len(rows), questions=len(grouped), target_correct=target_correct,
        reader_usage=usage, reader_token_equivalents_at_factor_one=overhead,
        half_allocation={name: grid[name][28] for name in conditions},
        half_allocation_question_bootstrap_95=intervals,
        gain_auc={name: auc([r['net'][name] for r in rows], [r['gain'] for r in rows]) for name in conditions},
        frontier=grid, matched_cost_sensitivity=sensitivity,
        equal_accuracy=equal, equal_accuracy_break_even_reader_token_factor=break_even,
        discordant=discordant, failures=failures,
        decision='stop' if failures else 'inconclusive' if intervals['Q'][0] <= 0 else 'review_protected_validation',
    )
    (HERE / 'RESULTS.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'frontier'}, indent=2))


if __name__ == '__main__':
    main()
