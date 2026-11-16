"""Question-grouped bootstrap for the Q vs P comparison.

Run from the repository root after build_sheet.py:
    python3 -B week7/scoring/bootstrap.py

Each resample draws 30 questions with replacement and keeps both seeds of each
drawn question, because two seeds of one question are not independent.
"""
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from frontier import load_rows, sweep
from overhead import READERS, charged, reader_cost

OUT = Path(__file__).resolve().parent / 'bootstrap-summary.json'
WEEK6 = Path(__file__).resolve().parents[2] / 'week6/research-handoff/results.json'
REPS = 10_000
SEED = 157222  # same seed as the frozen week 6 bootstrap


def fast_sweep(rows, column):
    # same curve as frontier.sweep, built one tie group at a time so 10k resamples stay quick
    order = sorted(rows, key=lambda r: -r[column])
    correct = sum(r['short_correct'] for r in rows)
    tokens = sum(r['short_tokens'] for r in rows)
    total_gains = sum(r['gain'] for r in rows)
    points = [dict(extensions=0, correct=correct, tokens=tokens, missed_gains=total_gains)]
    i = 0
    while i < len(order):
        group = [r for r in order[i:] if r[column] == order[i][column]]
        dc = sum(r['long_correct'] - r['short_correct'] for r in group)
        dt = sum(r['extra_tokens'] for r in group)
        dg = sum(r['gain'] for r in group)
        base = points[-1]
        # inside a tie group each extra slot takes an equal share of the group
        for k in range(1, len(group) + 1):
            f = k / len(group)
            points.append(dict(extensions=i + k, correct=base['correct'] + f * dc,
                               tokens=base['tokens'] + f * dt, missed_gains=base['missed_gains'] - f * dg))
        i += len(group)
    return points


def best_within(points, budget):
    return max(p['correct'] for p in points if p['tokens'] <= budget + 1e-9)


def cheapest_full(points):
    # fewest tokens that reach every correct answer available in this sample
    top = max(p['correct'] for p in points)
    return min(p['tokens'] for p in points if p['correct'] >= top - 1e-9)


def reader_wins(rows, q):
    # 1 if the reader, paying its measured cost, reaches full accuracy more cheaply than Q
    out = {}
    for name, (score, *_rest) in READERS.items():
        paid = charged(fast_sweep(rows, score), reader_cost(rows, name), len(rows))
        out[name] = int(cheapest_full(paid) < cheapest_full(q))
    return out


def measure(rows):
    n = len(rows)
    half = math.floor(0.5 * n)
    q, p = fast_sweep(rows, 'q_score'), fast_sweep(rows, 'p_score')
    return dict(
        wins=reader_wins(rows, q),
        # matched count; accuracy as a fraction, as in week 6
        count_accuracy_diff=(p[half]['correct'] - q[half]['correct']) / n,
        count_token_diff=p[half]['tokens'] - q[half]['tokens'],
        # matched cost
        cost_matched_correct_diff=best_within(p, q[half]['tokens']) - q[half]['correct'],
        # equal accuracy at full correctness
        headroom_per_prefix=(cheapest_full(q) - cheapest_full(p)) / n,
        missed_gains_q=q[half]['missed_gains'],
        missed_gains_p=p[half]['missed_gains'],
    )


def interval(values):
    # same percentile indices as the week 6 evaluation (249 and 9749 out of 10,000)
    v = sorted(values)
    return dict(low=v[int(0.025 * len(v)) - 1], median=v[len(v) // 2], high=v[int(0.975 * len(v)) - 1])


def main():
    rows = load_rows()
    for column in ['q_score', 'p_score']:
        a, b = fast_sweep(rows, column), sweep(rows, column)
        assert all(abs(x['correct'] - y['correct']) < 1e-9 and abs(x['tokens'] - y['tokens']) < 1e-6
                   for x, y in zip(a, b))

    by_question = defaultdict(list)
    for r in rows:
        by_question[int(r['question_id'])].append(r)
    ids = sorted(by_question)

    rng = random.Random(SEED)
    draws = []
    for _ in range(REPS):
        sample = [r for i in rng.choices(ids, k=len(ids)) for r in by_question[i]]
        draws.append(measure(sample))

    point = measure(rows)
    summary = {k: dict(observed=point[k], **interval([d[k] for d in draws])) for k in point if k != 'wins'}
    summary['reader_wins_share'] = {name: sum(d['wins'][name] for d in draws) / REPS for name in READERS}

    # reproduce the published week 6 intervals before writing
    published = json.loads(WEEK6.read_text())['question_prefix']
    for key, field in [('count_accuracy_diff', 'paired_question_bootstrap_accuracy_difference_ci95'),
                       ('count_token_diff', 'paired_question_bootstrap_token_difference_ci95')]:
        low, high = published[field]
        assert abs(summary[key]['low'] - low) < 1e-9 and abs(summary[key]['high'] - high) < 1e-9, key
    OUT.write_text(json.dumps(summary, indent=2) + '\n')

    labels = {
        'count_accuracy_diff': 'P-Q accuracy at N=half (fraction)',
        'count_token_diff': 'P-Q tokens at N=half',
        'cost_matched_correct_diff': 'P-Q correct at Q\'s half-allocation cost',
        'headroom_per_prefix': 'reader headroom per prefix (full accuracy)',
        'missed_gains_q': 'gains Q misses at N=half',
        'missed_gains_p': 'gains P misses at N=half',
    }
    print(f'{REPS:,} question-grouped resamples (seed {SEED})\n')
    print(f'   {"":44} {"observed":>10} {"2.5%":>10} {"median":>10} {"97.5%":>10}')
    for k, label in labels.items():
        s = summary[k]
        print(f'   {label:44} {s["observed"]:10,.3f} {s["low"]:10,.3f} {s["median"]:10,.3f} {s["high"]:10,.3f}')
    print('\nshare of resamples where a measured reader, using its own ranking and paying its')
    print('measured cost, reaches full accuracy more cheaply than Q')
    for name, share in summary['reader_wins_share'].items():
        print(f'   {share:6.1%}  {name} ({reader_cost(rows, name):,.0f}/prefix observed)')
    print(f'\nwrote {OUT.name}')


if __name__ == '__main__':
    main()
