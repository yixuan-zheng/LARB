"""Grade independently of generation and distinguish missing draws from wrong answers."""
import argparse
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

from common import extract_integer
from protocol import atomic, read, sha
from study import ARMS, HERE, completed, schedule, verify_release


def wilson(successes, count, z):
    p = successes/count
    scale = 1+z*z/count
    center = (p+z*z/(2*count))/scale
    half = z*math.sqrt(p*(1-p)/count+z*z/(4*count*count))/scale
    return [max(0., center-half), min(1., center+half)]


def estimates(calls):
    arms = {}
    for arm in ARMS:
        labels = calls[arm]
        n = len(labels)
        wins = sum(label == 1 for label in labels)
        missing = labels.count(None)
        arms[arm] = dict(planned=n, successes=wins, missing=missing,
                         probability=wins/n if missing == 0 else None,
                         missing_data_bounds=[wins/n, (wins+missing)/n],
                         wilson_95=wilson(wins,n,1.95996398454) if missing == 0 else None)
    short, long = (arms[arm] for arm in ARMS)
    lo_s, hi_s = short['missing_data_bounds']
    lo_l, hi_l = long['missing_data_bounds']
    delta = None
    interval = None
    gains = losses = None
    if short['missing'] + long['missing'] == 0:
        ps, pl = short['probability'], long['probability']
        delta, gains, losses = pl-ps, (1-ps)*pl, ps*(1-pl)
        sl, su = wilson(short['successes'], short['planned'], 2.2414027276)
        ll, lu = wilson(long['successes'], long['planned'], 2.2414027276)
        interval = [ll-su, lu-sl]
    return dict(arms=arms, delta=delta, independent_draw_gain=gains, independent_draw_loss=losses,
                delta_approx_95=interval, delta_missing_data_bounds=[lo_l-hi_s, hi_l-lo_s])


def grade(record, answer):
    if record is None:
        return None, 'missing'
    extracted = extract_integer(record['final_text'])
    if not record['normal']:
        return 0, record['reason']
    return int(extracted['value'] == answer), extracted['issue'] or 'graded'


def summarize(data, tasks, root, answers):
    grouped = defaultdict(lambda: defaultdict(list))
    grades = []
    for task in tasks:
        pair = data['prefixes'][task['prefix_key']]
        result = completed(root, task, data)
        label, reason = grade(result, answers[pair['id']])
        grouped[task['prefix_key']][task['arm']].append(label)
        grades.append(dict(call_id=task['call_id'], correct=label, reason=reason))
    rows = {key: estimates(value) for key, value in grouped.items()}
    question_groups = defaultdict(list)
    cohort = None
    if all(row['delta'] is not None for row in rows.values()):
        for key, row in rows.items():
            question_groups[data['prefixes'][key]['id']].append(row['delta'])
        rng = random.Random(781129)
        groups = list(question_groups.values())
        boot = sorted(statistics.mean(delta for group in rng.choices(groups, k=len(groups)) for delta in group)
                      for _ in range(10000))
        cohort = dict(mean_delta=statistics.mean(row['delta'] for row in rows.values()),
                      question_cluster_bootstrap_95=[boot[249], boot[9749]],
                      mean_p4=statistics.mean(row['arms']['short']['probability'] for row in rows.values()),
                      mean_p8=statistics.mean(row['arms']['long']['probability'] for row in rows.values()))
    bounds = [statistics.mean(row['delta_missing_data_bounds'][i] for row in rows.values()) for i in (0, 1)]
    return dict(prefixes=rows, cohort=cohort, cohort_delta_missing_data_bounds=bounds, grades=grades)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('questions', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    manifest = read(args.run/'manifest.json')
    assert manifest['release_sha256'] == verify_release()
    data = read(HERE/'prefixes.json')
    tasks = schedule(data, manifest['mode'])
    assert manifest['tasks'] == tasks
    assert sha(args.questions) == data['questions_sha256'], 'Unexpected answer-key file'
    answers = {item['id']: item['answer'] for item in read(args.questions)}
    result = summarize(data, tasks, args.run, answers)
    result.update(mode=manifest['mode'], planned=len(tasks))
    if manifest['mode'] == 'pilot':
        result['cohort'] = None
    if args.output.exists():
        raise FileExistsError(args.output)
    atomic(args.output, result)


if __name__ == '__main__':
    main()
