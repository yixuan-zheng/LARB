"""Evaluate sealed forecasts against the protected shared-prefix outcomes."""
import argparse
import hashlib
import itertools
import json
import random
import statistics
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'week6/aime-budget-screen'))
from common import extract_integer


def read(path):
    return json.loads(path.read_text())


def sealed(path):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == path.with_suffix('.sha256').read_text().strip()
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == len({row['case_id'] for row in rows})
    assert all(row['input_tokens'] > 0 and 0 < row['output_tokens'] <= 96 for row in rows)
    return {row['case_id']: row for row in rows}


def frontier(rows, policy, factor):
    early = [row for row in rows if not row['eligible']]
    active = [row for row in rows if row['eligible']]
    fixed_correct = sum(row['short_correct'] for row in rows)
    fixed_cost = sum(row['short_tokens'] for row in rows)
    fixed_cost += factor * sum(row['reader_tokens'][policy] for row in active)
    points = [(0, fixed_correct, fixed_cost, 0., 0.)]
    assert all(row['short_correct'] == row['long_correct'] for row in early)
    ordered = sorted(active, key=lambda row: row['rank'][policy], reverse=True)
    for _, group in itertools.groupby(ordered, key=lambda row: row['rank'][policy]):
        tied = list(group)
        count, correct, cost, gains, losses = points[-1]
        changes = [row['long_correct'] - row['short_correct'] for row in tied]
        dc = sum(changes)
        dt = sum(row['long_tokens'] - row['short_tokens'] for row in tied)
        dg = changes.count(1)
        dl = changes.count(-1)
        for taken in range(1, len(tied) + 1):
            weight = taken / len(tied)
            points.append((count + taken, correct + weight * dc, cost + weight * dt,
                           gains + weight * dg, losses + weight * dl))
    return points


def best_at(points, ceiling):
    feasible = [point for point in points if point[2] <= ceiling + 1e-9]
    return max(feasible, key=lambda point: (point[1], -point[2]), default=None)


def charged_comparison(rows, policies, factor):
    ranks = {policy: frontier(rows, policy, factor) for policy in policies}
    half = (len(ranks['question']) - 1) // 2
    ceiling = ranks['question'][half][2]
    return ceiling, {name: best_at(points, ceiling) for name, points in ranks.items()}, ranks


def net(row):
    p = row['probabilities']
    assert len(p) == 4 and all(0 <= value <= 1 for value in p) and abs(sum(p) - 1) < 1e-5
    return p[1] - p[2]


def tokens(row):
    return row['input_tokens'] + row['output_tokens']


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('readouts', type=Path)
    args = parser.parse_args()
    for name, expected in read(HERE / 'EVALUATION-SHA256.json').items():
        assert hashlib.sha256((HERE.parents[1] / name).read_bytes()).hexdigest() == expected, name
    mapping = read(args.readouts / 'mapping.json')
    direct = sealed(args.readouts / 'direct.jsonl')
    step = sealed(args.readouts / 'step.jsonl')
    assert set(direct) == set(mapping)
    assert set(step) == {case for case, row in mapping.items() if row['condition'] == 'bounded'}
    audit = read(args.readouts / 'audit-packet.json')
    audit_review = read(args.readouts / 'audit-review.json')
    assert {row['case_id'] for row in audit_review} == {row['case_id'] for row in audit}
    assert all(row.get('judgment') and row.get('notes') for row in audit_review)
    q = {row['key']: direct[case] for case, row in mapping.items() if row['condition'] == 'question'}
    b = {mapping[case]['key']: (direct[case], forecast) for case, forecast in step.items()}
    assert read(args.run / 'status.json')['complete'] and read(args.run / 'gate.json')['passed']
    answers = {row['id']: row['answer'] for row in read(args.run / 'questions.json')}
    grouped = {qid: [] for qid in answers}
    for item in read(args.run / 'schedule.json'):
        pair = read(args.run / 'pairs' / f"{item['key']}.json")
        assert pair['complete']
        active = pair['eligible']
        row = dict(key=item['key'], eligible=active)
        for branch in ('short', 'long'):
            result = pair['branches'][branch]
            grade = extract_integer(result['raw_output'])
            row[f'{branch}_correct'] = int(result['normal'] and grade['value'] == answers[item['id']])
            row[f'{branch}_tokens'] = len(result['token_ids'])
            if active:
                assert result['token_ids'][:4096] == pair['prefix_token_ids']
        if active:
            question = q[str(item['id'])]
            bounded, operation = b[item['key']]
            tier = {'READY': 0, 'INSUFFICIENT': 1, 'STEP': 2}[operation['decision']]
            row['rank'] = dict(question=net(question), direct=net(bounded), step=(tier, net(question)))
            row['reader_tokens'] = dict(question=tokens(question), direct=tokens(bounded), step=tokens(question) + tokens(operation))
        grouped[item['id']].append(row)
    assert len(grouped) == 30 and all(len(group) == 2 for group in grouped.values())
    rows = [row for group in grouped.values() for row in group]
    assert {row['key'] for row in rows if row['eligible']} == set(b)
    policies = ['question', 'direct', 'step']
    sensitivity = {}
    for factor in [0, .25, .5, 1, 2]:
        ceiling, best, ranks = charged_comparison(rows, policies, factor)
        sensitivity[str(factor)] = dict(ceiling=ceiling, best=best)
        if factor == 1:
            primary = best
            full_frontier = ranks
    discordant = sum(row['short_correct'] != row['long_correct'] for row in rows)
    rng = random.Random(761226)
    deltas = []
    infeasible = 0
    for _ in range(10000):
        sample = [row for group in rng.choices(list(grouped.values()), k=len(grouped)) for row in group]
        _, best, _ = charged_comparison(sample, ['question', 'step'], 1)
        if best['step'] is None:
            infeasible += 1
            continue
        deltas.append((best['step'][1] - best['question'][1]) / len(sample))
    interval = statistics.quantiles(deltas, n=40, method='inclusive') if len(deltas) >= 2 else None
    bounds = [interval[0], interval[-1]] if interval else None
    delta = primary['step'][1] - primary['question'][1] if primary['step'] else None
    decision = 'stop'
    if discordant < 4:
        decision = 'low_information'
    elif delta is not None and delta >= 2 - 1e-9:
        decision = 'review_serving_feasibility' if bounds and bounds[0] > 0 and not infeasible else 'inconclusive'
    result = dict(
        point_columns=['extensions', 'expected_correct', 'charged_tokens', 'gains', 'losses'],
        population=len(rows), eligible=len(b), discordant=discordant,
        fixed_short_correct=sum(r['short_correct'] for r in rows),
        fixed_long_correct=sum(r['long_correct'] for r in rows),
        half_allocation={name: points[len(b)//2] for name, points in full_frontier.items()},
        step_decisions={name: sum(r['decision'] == name for r in step.values())
                        for name in ('STEP', 'READY', 'INSUFFICIENT')},
        warm_median_seconds={name: statistics.median(r['seconds'] for r in forecasts)
                             for name, forecasts in [('question', list(q.values())),
                                                    ('direct', [x[0] for x in b.values()]),
                                                    ('step', list(step.values()))] if forecasts},
        sensitivity=sensitivity, charged_frontier=full_frontier, delta_correct=delta,
        question_bootstrap_95=bounds, bootstrap_infeasible=infeasible, decision=decision,
    )
    with (args.readouts / 'RESULTS.json').open('x') as output:
        json.dump(result, output, indent=2)
        output.write('\n')
    print(decision)


if __name__ == '__main__':
    main()
