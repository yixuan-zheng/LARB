"""Compare sealed full-prefix and question-only forecasts."""
import hashlib
import itertools
import json
import random
import sys
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'week6/question-prefix-comparison'))
sys.path.insert(0, str(REPO / 'week6/aime-budget-screen'))
from evaluate import allocation, auc
from common import extract_integer

OUTCOMES = ['ww', 'wc', 'cw', 'cc']
EXTENSIONS = {'week6': 28, 'week7': 29}
ARMS = ['question', 'prefix']


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probabilities(record):
    values = [record[name] for name in OUTCOMES]
    if not all(type(p) is int and 0 <= p <= 100 for p in values) or sum(values) != 100:
        raise ValueError('Expected four integer percentages summing to 100')
    if not isinstance(record['explanation'], str) or not record['explanation'].strip():
        raise ValueError('Missing explanation')
    return values


def outcomes():
    week6 = REPO / 'week6/shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'
    week7 = HERE.parent / 'recoverable-step/results/job-6958397'
    for pair in read(week6 / 'graded-pairs.json'):
        if pair['eligible']:
            yield 'week6', pair['id'], pair['key'], pair['outcomes']
    answers = {q['id']: q['answer'] for q in read(week7 / 'questions.json')}
    for item in read(week7 / 'schedule.json'):
        pair = read(week7 / 'pairs' / f"{item['key']}.json")
        if pair['eligible']:
            result = {}
            for branch, raw in pair['branches'].items():
                result[branch] = dict(correct=raw['normal'] and extract_integer(raw['raw_output'])['value'] == answers[item['id']],
                                      tokens=len(raw['token_ids']))
            yield 'week7', item['id'], item['key'], result


def metrics(rows, arm):
    reliability = {}
    for i, outcome in enumerate(OUTCOMES):
        bins = [[] for _ in range(5)]
        for row in rows:
            p = row['forecast'][arm][i]
            bins[min(p // 20, 4)].append((p, row['outcome'] == outcome))
        reliability[outcome] = [
            dict(count=len(group), mean_prediction=sum(x for x, _ in group)/len(group)/100,
                 realized_frequency=sum(y for _, y in group)/len(group)) if group else dict(count=0)
            for group in bins
        ]
    return dict(gain_auc=auc([r['net'][arm] for r in rows], [r['gain'] for r in rows]),
                joint_brier=sum(sum((r['forecast'][arm][i]/100-(r['outcome']==o))**2
                                    for i, o in enumerate(OUTCOMES)) for r in rows)/len(rows),
                reliability=reliability)


def evaluate(rows, n):
    results = {}
    for arm in ARMS:
        result = allocation(rows, arm, n)
        result['expected_losses_captured'] = (
            sum(r['short_correct'] for r in rows) + result['expected_gains_captured'] - result['expected_correct']
        )
        results[arm] = result
    return results


def main():
    for name, digest in read(HERE/'evaluation-lock.json').items():
        assert sha(REPO/name) == digest, name
    forecast_file = HERE/'forecasts.jsonl'
    seal = read(HERE/'forecast-seal.json')
    assert seal['forecast_sha256'] == sha(forecast_file)
    assert seal['reader_lock_sha256'] == sha(HERE/'reader-lock.json')
    reader_lock = read(HERE/'reader-lock.json')
    for name, digest in reader_lock['files'].items():
        assert sha(HERE/name) == digest, name
    mapping = read(HERE/'mapping.json')
    forecasts = {}
    for line in forecast_file.read_text().splitlines():
        record = json.loads(line)
        case = record['case_id']
        identity = tuple(mapping[case])
        assert identity not in forecasts
        forecasts[identity] = probabilities(record)
    assert set(forecasts) == {tuple(item) for item in mapping.values()}

    groups = {name: defaultdict(list) for name in EXTENSIONS}
    for cohort, question, key, raw in outcomes():
        short, long = (int(raw[arm]['correct']) for arm in ['short', 'long'])
        forecast = {arm: forecasts[cohort, arm, item] for arm, item in [('question', question), ('prefix', key)]}
        row = dict(key=key, outcome=('c' if short else 'w') + ('c' if long else 'w'), gain=long > short,
                   short_correct=short, long_correct=long, short_tokens=raw['short']['tokens'],
                   long_tokens=raw['long']['tokens'], forecast=forecast,
                   net={arm: p[1]-p[2] for arm, p in forecast.items()})
        groups[cohort][question].append(row)
    cohorts = {}
    pooled = 0
    for cohort, group in groups.items():
        rows = list(itertools.chain.from_iterable(group.values()))
        assert len(rows) == 2 * EXTENSIONS[cohort] + (cohort == 'week6')
        comparisons = evaluate(rows, EXTENSIONS[cohort])
        delta = comparisons['prefix']['expected_correct'] - comparisons['question']['expected_correct']
        pooled += delta
        discordant = []
        for q, items in group.items():
            if len(items) != 2:
                continue
            first, second = sorted(items, key=lambda r: r['long_correct']-r['short_correct'], reverse=True)
            if first['long_correct']-first['short_correct'] > second['long_correct']-second['short_correct']:
                discordant.append(dict(question=q, higher_net=first['key'], lower_net=second['key'],
                                       higher_outcome=first['outcome'], lower_outcome=second['outcome'],
                                       prefix_score_gap=first['net']['prefix']-second['net']['prefix']))
        cohorts[cohort] = dict(eligible=len(rows), comparisons=comparisons, delta_correct=delta,
                               metrics={arm: metrics(rows, arm) for arm in ARMS}, discordant=discordant)
    rng = random.Random(781127)
    samples = {name: [] for name in [*EXTENSIONS, 'pooled']}
    for _ in range(10000):
        total = count = 0
        for cohort, group in groups.items():
            values = list(group.values())
            rows = list(itertools.chain.from_iterable(rng.choices(values, k=len(values))))
            result = evaluate(rows, len(rows)//2)
            delta = result['prefix']['expected_correct'] - result['question']['expected_correct']
            samples[cohort].append(delta/len(rows))
            total += delta
            count += len(rows)
        samples['pooled'].append(total/count)
    intervals = {name: [sorted(values)[i] for i in [249, 9749]] for name, values in samples.items()}
    decision = 'inconclusive'
    minimum = 4/115
    if pooled >= 4-1e-9 and intervals['pooled'][0] > 0 and all(c['delta_correct'] > 0 for c in cohorts.values()):
        decision = 'advance_stage_2'
    elif intervals['pooled'][1] < minimum:
        decision = 'worthwhile_effect_excluded'
    with (HERE/'RESULTS.json').open('x') as output:
        json.dump(dict(cohorts=cohorts, pooled_delta_correct=pooled, pooled_delta_accuracy=pooled/115,
                       bootstrap_95=intervals, decision=decision), output, indent=2)
        output.write('\n')


if __name__ == '__main__':
    main()
