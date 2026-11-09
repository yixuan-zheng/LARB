"""Reproduce paired outcomes and apply the predeclared diagnostic gates."""
import argparse
import math
import random
import sys
from collections import Counter
from pathlib import Path

from protocol import HERE, REPO, atomic, read, schedule, sha
sys.path.insert(0,str(REPO/'week6/aime-budget-screen'))
from common import extract_integer


def rows(root, split):
    questions = {q['id']:q for q in read(HERE/'inputs/questions.json')}
    result = []
    for item in schedule():
        if item['split'] != split:
            continue
        path = root/'pairs'/f"{item['key']}.json"
        pair = read(path) if path.exists() else {}
        row = dict(**item,eligible=pair.get('eligible',False),score=pair.get('score'),
                   complete=pair.get('complete',False),outcomes={})
        for branch in ['short','long']:
            raw = pair.get('branches',{}).get(branch,{})
            grade = extract_integer(raw.get('raw_output',''))
            row['outcomes'][branch] = dict(
                correct=bool(raw.get('normal') and grade['value']==questions[item['id']]['answer']),
                # Incomplete costs cannot support a favorable budget claim.
                tokens=len(raw.get('token_ids',[])) if raw else None,
                issue=grade.get('issue'), reason=raw.get('reason','missing'),
                extracted=grade.get('value'), reference=questions[item['id']]['answer'])
        result.append(row)
    return result


def choose(row, rule):
    if not row['eligible']:
        return 'short'
    if rule['kind']=='long':
        return 'long'
    if rule['kind']=='short':
        return 'short'
    return 'long' if row['score'] < rule['threshold'] else 'short'


def metrics(data, rule):
    outcomes = [r['outcomes'][choose(r,rule)] for r in data]
    return dict(correct=sum(o['correct'] for o in outcomes),
                tokens=sum(o['tokens'] or 0 for o in outcomes),
                continued=sum(r['eligible'] and choose(r,rule)=='long' for r in data))


def seal_calibration(root):
    target = root/'calibration-seal.json'
    assert not target.exists(), 'calibration already sealed'
    data = rows(root,'calibration')
    assert len(data)==20 and all(r['complete'] for r in data), 'incomplete calibration'
    scores = sorted(r['score'] for r in data if r['eligible'])
    candidates = [dict(kind='short'),dict(kind='long')]
    for quantile in [0,0.25,0.5,0.75,1]:
        if scores:
            index = (len(scores)-1)*quantile
            low, high = math.floor(index),math.ceil(index)
            threshold = scores[low]+(scores[high]-scores[low])*(index-low)
            candidates.append(dict(kind='threshold',quantile=quantile,threshold=threshold))
    fixed_long = metrics(data,dict(kind='long'))
    feasible = [(rule,metrics(data,rule)) for rule in candidates]
    feasible = [(rule,m) for rule,m in feasible if m['tokens']<=0.85*fixed_long['tokens']]
    feasible.sort(key=lambda rm:(-rm[1]['correct'],rm[1]['tokens'],-rm[1]['continued']))
    atomic(target,dict(rule=feasible[0][0] if feasible else None,
                      feasible_candidates=feasible,
                      calibration_pair_sha256={r['key']:sha(root/'pairs'/f"{r['key']}.json") for r in data},
                      status='sealed_before_evaluation'))


def frontier(data):
    # For each attainable correctness count retain the cheapest assignment.
    dp = {0:0}
    for row in data:
        next_dp = {}
        for count,cost in dp.items():
            for outcome in row['outcomes'].values():
                new_count = count+int(outcome['correct'])
                new_cost = cost+outcome['tokens']
                next_dp[new_count] = min(new_cost,next_dp.get(new_count,new_cost))
        dp = next_dp
    return [dict(correct=k,tokens=v) for k,v in sorted(dp.items())]


def percentile(values, fraction):
    values = sorted(values)
    return values[int((len(values)-1)*fraction)]


def analyze(root):
    data = rows(root,'evaluation')
    calibration = rows(root,'calibration')
    atomic(root/'graded-pairs.json',calibration+data)
    atomic(root/'extraction-review.json',[r for r in calibration+data
        if any(o['issue'] or o['reason']!='normal' for o in r['outcomes'].values())])
    gate = root/'gate.json'
    if (not gate.exists() or not read(gate)['passed'] or not all(r['complete'] for r in calibration+data)
        or not (root/'calibration-seal.json').exists()):
        atomic(root/'decision.json',dict(decision='inconclusive',reason='gate, coverage, or calibration seal failure',
               present_complete_pairs=sum(r['complete'] for r in calibration+data),planned=60))
        return
    sealed = read(root/'calibration-seal.json')
    assert sealed['calibration_pair_sha256']=={
        r['key']:sha(root/'pairs'/f"{r['key']}.json") for r in calibration}
    fixed_short = metrics(data,dict(kind='short'))
    fixed_long = metrics(data,dict(kind='long'))
    ceiling = int(0.85*fixed_long['tokens'])
    options = frontier(data)
    feasible = [o for o in options if o['tokens']<=ceiling]
    oracle = max(feasible,key=lambda x:x['correct']) if feasible else None
    eligible = [r for r in data if r['eligible']]
    transitions = Counter(f"{int(r['outcomes']['short']['correct'])}->{int(r['outcomes']['long']['correct'])}"
                          for r in eligible)
    discordant = transitions['0->1']+transitions['1->0']
    opportunity = bool(oracle and oracle['correct']>=fixed_long['correct']
                       and oracle['correct']>=fixed_short['correct']+2)
    result = dict(fixed_short=fixed_short,fixed_long=fixed_long,ceiling=ceiling,
        oracle=oracle,frontier=options,eligible=len(eligible),transitions=dict(transitions),
        opportunity_pass=opportunity,selector_rule=sealed['rule'])
    if len(eligible)<=10 or discordant<4:
        result.update(decision='inconclusive',reason='low eligible coverage or fewer than four discordant pairs')
    elif not opportunity:
        result.update(decision='stop',reason='oracle opportunity criterion failed')
    elif sealed['rule'] is None:
        result.update(decision='stop',reason='no feasible calibration selector')
    else:
        rule=sealed['rule']
        selected=metrics(data,rule)
        rng=random.Random(56222)
        random_correct=[]
        equal_rate=[]
        count=selected['continued']
        for _ in range(10000):
            picked=set(rng.sample(range(len(eligible)),count))
            chosen={r['key'] for i,r in enumerate(eligible) if i in picked}
            outcomes=[r['outcomes']['long' if r['key'] in chosen else 'short'] for r in data]
            correct=sum(o['correct'] for o in outcomes)
            equal_rate.append(correct)
            if sum(o['tokens'] for o in outcomes)<=ceiling:
                random_correct.append(correct)
        # Matched cost results use the declared same-rate random assignments
        # satisfying the ceiling. Report feasible sample count explicitly.
        deltas=[];ratios=[]
        ids=sorted({r['id'] for r in data})
        by_id={i:[r for r in data if r['id']==i] for i in ids}
        for _ in range(10000):
            sample=[r for i in rng.choices(ids,k=len(ids)) for r in by_id[i]]
            a=metrics(sample,rule);s=metrics(sample,dict(kind='short'));l=metrics(sample,dict(kind='long'))
            deltas.append((a['correct']-s['correct'])/len(sample))
            ratios.append(a['tokens']/l['tokens'])
        lower=percentile(deltas,0.025)
        random_mean=sum(random_correct)/len(random_correct) if random_correct else None
        point=bool(selected['tokens']<=ceiling and selected['correct']>=fixed_long['correct']
            and selected['correct']-fixed_short['correct']>=0.5*(oracle['correct']-fixed_short['correct'])
            and random_mean is not None and selected['correct']>random_mean)
        blocks=[]
        for block in [0,1]:
            b=[r for r in data if r['block']==block]
            blocks.append(dict(block=block,selected=metrics(b,rule),fixed_long=metrics(b,dict(kind='long'))))
        stable=all(b['selected']['correct']>=b['fixed_long']['correct']-1 for b in blocks)
        decision='earn_concurrent_review' if point and stable and lower>0 else 'stop'
        if point and (not stable or lower<=0):
            decision='inconclusive'
        result.update(decision=decision,selected=selected,blocks=blocks,
            accuracy_delta_vs_short_ci95=[lower,percentile(deltas,0.975)],
            token_ratio_ci95=[percentile(ratios,0.025),percentile(ratios,0.975)],
            same_rate_random_mean=sum(equal_rate)/len(equal_rate),
            matched_ceiling_random_mean=random_mean,matched_ceiling_random_samples=len(random_correct),
            overhead_sensitivity=[dict(service_time_overhead=x) for x in [0,0.01,0.05,0.10]],
            note='Conditional question bootstrap holds calibration rule fixed. Timings require separate overhead accounting.')
    atomic(root/'decision.json',result)
    print(result['decision'])


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('root',type=Path)
    analyze(parser.parse_args().root)
