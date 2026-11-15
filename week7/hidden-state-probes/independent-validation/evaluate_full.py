"""Offline, complete-coverage-only evaluation of the sealed validation."""
import argparse
import csv
import json
from pathlib import Path
import sys

import numpy as np


def weights(scores):
    k = len(scores)//2
    if not k:
        return np.zeros(len(scores))
    cutoff = np.partition(scores, len(scores)-k)[-k]
    above, tied = scores > cutoff, scores == cutoff
    return above + tied*(k-above.sum())/tied.sum()


def evaluate(rates, costs, scores, question, all_questions):
    delta = rates[:,1]-rates[:,0]
    allocations = {n:weights(s) for n,s in scores.items()}
    results = {}
    for name, w in {**allocations, 'all_short':np.zeros(len(delta)),
                    'all_long':np.ones(len(delta))}.items():
        cost = costs[:,0] + w[:,None]*(costs[:,1]-costs[:,0])
        results[name] = dict(expected_correct=float(rates[:,0].sum()+w@delta),
            beneficial_selected=float(w@(delta>0)), harmful_selected=float(w@(delta<0)),
            beneficial_missed=float((1-w)@(delta>0)), gains=float(w@np.maximum(delta,0)),
            losses=float(w@np.maximum(-delta,0)),
            **dict(zip(('suffix_tokens','input_tokens','seconds'),cost.sum(axis=0).tolist())))
    groups = [np.flatnonzero(question==q) for q in all_questions]
    rng = np.random.default_rng(356)
    boot = []
    for _ in range(10000):
        ix = np.concatenate([groups[j] for j in rng.integers(len(groups),size=len(groups))])
        if len(ix):
            boot.append(float((weights(scores['mean_4k'][ix])-weights(scores['prompt'][ix]))@delta[ix]/len(ix)))
    lift = float((allocations['mean_4k']-allocations['prompt'])@delta)
    interval = np.quantile(boot,[.025,.975])
    lift_rate = lift/len(delta)
    threshold = 2/58
    decision = ('positive' if lift_rate >= threshold and interval[0] > 0 else
                'below_practical_threshold' if interval[1] < threshold else 'inconclusive')
    paired = [g for g in groups if len(g)==2]
    distinct = [g for g in paired if delta[g[0]] != delta[g[1]]]
    within = {}
    for name, s in scores.items():
        points = []
        for a,b in distinct:
            direction = (s[a]-s[b])*(delta[a]-delta[b])
            points.append(1. if direction > 0 else .5 if direction == 0 else 0.)
        within[name] = float(np.mean(points)) if points else None
    return dict(eligible=len(delta), allocations=results, lift_expected_correct=lift,
                lift_pp=100*lift_rate, ci95_pp=(100*interval).tolist(),
                ci95_expected_correct=(len(delta)*interval).tolist(), decision=decision,
                within_question=dict(paired_questions=len(paired), distinct_empirical_delta=len(distinct),
                                     concordance=within))


def main():
    parser = argparse.ArgumentParser()
    for field in ('release','run','source_csv','grader','output'):
        parser.add_argument(field,type=Path)
    args = parser.parse_args()
    sys.path.insert(0,str(args.release))
    from full_gpu import plan_suffix
    from gate_workflow import grading_ready
    from protocol import read, sha
    from study import completed, verify_release
    # The isolated original grader is loaded only after coverage verification.
    digest = verify_release(args.release)
    root, gate = args.run, args.run.parent/'gate'
    grading_ready(root,digest)
    for name, expected in read(args.release/'gate-evidence-lock.json').items():
        assert sha(gate/name)==expected
    prefix_rows = read(root/'prefix-selection.json')
    forecast = read(root/'forecasts.json')
    for r,f in zip(prefix_rows,forecast,strict=True):
        assert r['task']['prefix_key']==f['key'] and r['input_hash']==f['input_hash']
    planned = plan_suffix(read(args.release/'seed-ledger.json'),prefix_rows)
    assert read(root/'suffix'/'manifest.json')['tasks']==planned
    data = dict(prefixes={r['task']['prefix_key']:dict(prompt_token_ids=r['prompt'],
                prefix_token_ids=r['tokens'],prefix_hash=r['prefix_hash']) for r in prefix_rows})
    records = {}
    for task in planned:
        local = completed(root/'suffix',task,data)
        earlier = completed(gate/'suffix',task,data)
        assert (local is None) != (earlier is None), task['call_id']
        record = local or earlier
        directory = root/'suffix' if local is not None else gate/'suffix'
        assert read(directory/'attempts'/task['call_id']/record['attempt'])['status']=='committed'
        records[task['call_id']] = record
    assert len(records)==16*len(prefix_rows)
    cohort = read(args.release/'cohort-v1.json')
    assert sha(args.source_csv)==cohort['source_sha256']
    sys.path.insert(0,str(args.grader))
    from score import grade
    with args.source_csv.open(newline='', encoding='utf-8-sig') as handle:
        selected = {r['id'] for r in cohort['selected']}
        keys = {r['ID']:int(r['Answer']) for r in csv.DictReader(handle) if r['ID'] in selected}
    rates = np.empty((len(prefix_rows),2))
    costs = np.empty((len(prefix_rows),2,3))
    for i,row in enumerate(prefix_rows):
        key, question = row['task']['prefix_key'], row['task']['question']
        for j,arm in enumerate(('short','long')):
            samples = [records[f'{key}-{arm}-{k:02d}'] for k in range(8)]
            rates[i,j] = np.mean([grade(r,keys[question])[0] for r in samples])
            costs[i,j] = np.mean([[len(r['suffix_token_ids']),r['input_tokens'],r['elapsed_seconds']]
                                  for r in samples],axis=0)
    scores = {n:np.array([r['forecast'][n][1]-r['forecast'][n][0] for r in forecast])
              for n in ('prompt','mean_4k')}
    for n,s in scores.items():
        np.testing.assert_array_equal(weights(s),[r['weights'][n] for r in forecast])
    result = evaluate(rates,costs,scores,np.array([r['task']['question'] for r in prefix_rows]),sorted(keys))
    result['collected_suffix_cost'] = dict(zip(('tokens','input_tokens','seconds'),
                                               (8*costs.sum(axis=(0,1))).tolist()))
    with args.output.open('x') as handle:
        json.dump(result,handle,indent=2)
        handle.write('\n')


if __name__=='__main__':
    main()
