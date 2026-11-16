"""Sweep every extension count for question-only (Q) and prefix (P) scores, then
report misses, harms and within-question concordance for every score (rule 5).

Run from the repository root after build_sheet.py:
    python3 -B week7/scoring/frontier.py
"""
import csv
from collections import defaultdict
from pathlib import Path

from build_sheet import top_count

HERE = Path(__file__).resolve().parent
SHEET = HERE / 'prefix-sheet.csv'
OUT = HERE / 'frontier.csv'
POLICIES = {'Q': 'q_score', 'P': 'p_score'}
LABELS = {
    'q_score': 'question-only, archived',
    'p_score': 'week 6 full-prefix readers',
    'b_score': 'bounded 512-token reader',
    'bq_score': 'bounded reader, question only',
    'f_score': '27b full-prefix reader',
    'fq_score': '27b reader, question only',
}


def load_rows():
    rows = []
    with open(SHEET) as f:
        for r in csv.DictReader(f):
            for name in ['short_correct', 'long_correct', 'short_tokens', 'long_tokens', 'extra_tokens',
                         'b_in', 'b_out', 'f_in', 'f_out']:
                r[name] = int(r[name])
            for name in ['q_score', 'p_score', 'b_score', 'f_score', 'bq_score', 'fq_score', 'b_sec', 'f_sec']:
                r[name] = float(r[name])
            r['gain'] = r['outcome'] == 'wc'
            rows.append(r)
    return rows


def sweep(rows, column):
    # tied scores at the cutoff are split evenly, so counts can be fractional expectations
    total_gains = sum(r['gain'] for r in rows)
    points = []
    for n in range(len(rows) + 1):
        w = top_count(rows, column, n)
        correct = sum(r['short_correct'] + x * (r['long_correct'] - r['short_correct']) for r, x in zip(rows, w))
        tokens = sum(r['short_tokens'] + x * r['extra_tokens'] for r, x in zip(rows, w))
        gains = sum(x for r, x in zip(rows, w) if r['gain'])
        points.append(dict(extensions=n, correct=correct, tokens=tokens,
                           gains_captured=gains, missed_gains=total_gains - gains))
    return points


def cheapest_for(points, target):
    # equal-accuracy endpoint
    hits = [p['tokens'] for p in points if p['correct'] >= target - 1e-9]
    return min(hits) if hits else None


def best_within(points, budget):
    # matched-cost endpoint
    hits = [p['correct'] for p in points if p['tokens'] <= budget + 1e-9]
    return max(hits) if hits else None


def concordance(rows, column):
    # seeds of one question whose benefit differs; credit 1 if the seed that gains more
    # scores higher, 0.5 on a tie (experiment 3 rule, so question-only gets exactly 50%)
    by_question = defaultdict(list)
    for r in rows:
        by_question[r['question_id']].append(r)
    points = []
    for pair in by_question.values():
        if len(pair) != 2:
            continue
        a, b = pair
        benefit = (a['long_correct'] - a['short_correct']) - (b['long_correct'] - b['short_correct'])
        if benefit:
            d = (a[column] - b[column]) * benefit
            points.append(1.0 if d > 0 else 0.5 if d == 0 else 0.0)
    return sum(points) / len(points), len(points)


def main():
    rows = load_rows()
    curves = {name: sweep(rows, column) for name, column in POLICIES.items()}

    with open(OUT, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['policy', 'extensions', 'correct', 'tokens', 'gains_captured', 'missed_gains'])
        for name, points in curves.items():
            for p in points:
                writer.writerow([name, p['extensions'], round(p['correct'], 3), round(p['tokens'], 1),
                                 round(p['gains_captured'], 3), round(p['missed_gains'], 3)])
    print(f'wrote {OUT.relative_to(HERE.parents[1])}\n')

    q, p = curves['Q'], curves['P']
    print('1) matched extension count (original week 6 endpoint, STOP stays recorded)')
    for n in [14, 28, 42]:
        print(f'   N={n:2d}  Q {q[n]["correct"]:5.1f} correct / {q[n]["tokens"]:9,.0f} tok'
              f'   P {p[n]["correct"]:5.1f} / {p[n]["tokens"]:9,.0f}   P-Q tokens {p[n]["tokens"] - q[n]["tokens"]:+,.0f}')

    print('\n2) matched realized cost (most correct within the token budget)')
    for budget in range(330_000, 500_001, 20_000):
        print(f'   {budget:9,} tok   Q {best_within(q, budget):5.1f}   P {best_within(p, budget):5.1f}')

    print('\n3) equal accuracy (fewest tokens to reach the target)')
    for target in range(21, 29):
        qt, pt = cheapest_for(q, target), cheapest_for(p, target)
        print(f'   {target} correct   Q {qt:9,.0f}   P {pt:9,.0f}   P saves {qt - pt:+9,.0f}'
              f'  (= {(qt - pt) / len(rows):,.0f} tok per prefix)')

    half = len(rows) // 2
    print(f'\n4) misses, harms and within-question concordance at half allocation (N={half})')
    harmful = sum(r['outcome'] == 'cw' for r in rows)
    print(f'   harmful checkpoints in this cohort: {harmful}, so the harms check cannot fail on it')
    found = {}
    for column, label in LABELS.items():
        w = top_count(rows, column, half)
        missed = sum(1 - x for r, x in zip(rows, w) if r['gain'])
        harms = sum(x for r, x in zip(rows, w) if r['outcome'] == 'cw')
        found[column], pairs = concordance(rows, column)
        print(f'   {label:30} missed gains {missed:4.1f}   harmful selected {harms:3.1f}'
              f'   concordance {found[column]:4.0%} on {pairs} questions')
    # published counts: week 6 prefix readers and the 27b reader 3 of 4, bounded reader 1 of 4
    assert (found['p_score'], found['f_score'], found['b_score']) == (0.75, 0.75, 0.25)


if __name__ == '__main__':
    main()
