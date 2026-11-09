"""Frozen comparison of blinded forecasts and existing branch outcomes."""
import csv
import hashlib
import itertools
import json
import math
import random
import statistics
from collections import defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'
OUTCOMES=['ww','wc','cw','cc']


def read(path):
    return json.loads(path.read_text())


def auc(scores,truth):
    positive=[s for s,y in zip(scores,truth) if y]
    negative=[s for s,y in zip(scores,truth) if not y]
    if not positive or not negative:
        return None
    return sum((a>b)+0.5*(a==b) for a in positive for b in negative)/(len(positive)*len(negative))


def average_precision(scores,truth):
    """Expected AP over uniformly random ordering inside each tied score."""
    positives=sum(truth)
    if not positives:
        return None
    ordered=sorted(zip(scores,truth),reverse=True)
    before=0
    before_positive=0
    result=0.
    for score,values in itertools.groupby(ordered,key=lambda value:value[0]):
        group=list(values)
        size=len(group)
        count=sum(y for _,y in group)
        if count:
            for position in range(1,size+1):
                cumulative=before_positive+1
                if size>1:
                    cumulative+=(position-1)*(count-1)/(size-1)
                result+=(count/size)*cumulative/(before+position)/positives
        before+=size
        before_positive+=count
    return result


def selection_weights(scores,count):
    """Expected top-count membership, without outcome-dependent tie breaks."""
    assert 0<=count<=len(scores)
    if count==0:
        return [0.]*len(scores)
    threshold=sorted(scores,reverse=True)[count-1]
    higher=sum(s>threshold for s in scores)
    tied=sum(s==threshold for s in scores)
    fraction=(count-higher)/tied
    return [1. if s>threshold else fraction if s==threshold else 0. for s in scores]


def allocation(rows,condition,count):
    scores=[r['net'][condition] for r in rows]
    weights=selection_weights(scores,count)
    correct=sum(r['short_correct']+w*(r['long_correct']-r['short_correct']) for r,w in zip(rows,weights))
    tokens=sum(r['short_tokens']+w*(r['long_tokens']-r['short_tokens']) for r,w in zip(rows,weights))
    gains=sum(w for r,w in zip(rows,weights) if r['gain'])
    partial=sum(0<w<1 for w in weights)
    return dict(extensions=count,expected_correct=correct,expected_tokens=tokens,
                expected_gains_captured=gains,partially_selected_tied_cases=partial)


def prediction_metrics(rows,condition):
    truth=[r['gain'] for r in rows]
    net=[r['net'][condition] for r in rows]
    probabilities=[r['probabilities'][condition] for r in rows]
    return dict(gain_auc_net=auc(net,truth),
                gain_auc_probability=auc([p[1] for p in probabilities],truth),
                gain_average_precision=average_precision(net,truth),
                joint_brier=statistics.mean(sum((p[j]-int(r['outcome']==OUTCOMES[j]))**2 for j in range(4))
                                           for r,p in zip(rows,probabilities)),
                net_benefit_mse=statistics.mean((p[1]-p[2]-(r['long_correct']-r['short_correct']))**2
                                                for r,p in zip(rows,probabilities)))


def correlation(first,second):
    if statistics.pstdev(first)==0 or statistics.pstdev(second)==0:
        return None
    a,b=statistics.mean(first),statistics.mean(second)
    numerator=sum((x-a)*(y-b) for x,y in zip(first,second))
    denominator=math.sqrt(sum((x-a)**2 for x in first)*sum((y-b)**2 for y in second))
    return numerator/denominator


def main():
    plan=read(HERE/'PLAN.json')
    seal=read(HERE/'reader-seal.json')
    mapping=read(HERE/'private-mapping.json')
    frozen=read(HERE/'freeze-sha256.json')
    annotations={}
    for reader in ['q1','q2','p1','p2']:
        path=HERE/reader/'annotations.jsonl'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==seal[reader]['annotations_sha256']
        entries=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert len(entries)==(30 if reader.startswith('q') else 57)
        assert len({r['case_id'] for r in entries})==len(entries)
        output={}
        for entry in entries:
            packet_path=HERE/reader/'cases'/f"{entry['case_id']}.json"
            original=Path(plan['packet_roots'][reader])/'cases'/packet_path.name
            assert hashlib.sha256(packet_path.read_bytes()).hexdigest()==frozen[str(original)]
            packet=read(packet_path)
            assert all(type(entry[name]) is int and 0<=entry[name]<=100 for name in OUTCOMES)
            assert sum(entry[name] for name in OUTCOMES)==100
            source=packet.get('prefix',packet['question'])
            assert entry['evidence'] in source and 0<len(entry['evidence'])<=300
            assert entry['rationale'].strip()
            output[str(mapping[reader][entry['case_id']])]=entry
        annotations[reader]=output
    graded=read(ROOT/'graded-pairs.json')
    rows=[]
    for item in sorted([r for r in graded if r['eligible']],key=lambda x:x['key']):
        short,long=[int(item['outcomes'][branch]['correct']) for branch in ['short','long']]
        outcome=('c' if short else 'w')+('c' if long else 'w')
        probabilities={}
        net={}
        for reader in ['q1','q2','p1','p2']:
            key=str(item['id']) if reader.startswith('q') else item['key']
            forecast=annotations[reader][key]
            probabilities[reader]=[forecast[name]/100 for name in OUTCOMES]
            net[reader]=forecast['wc']-forecast['cw']
        for condition,readers in [('Q',['q1','q2']),('P',['p1','p2'])]:
            probabilities[condition]=[statistics.mean(probabilities[r][i] for r in readers) for i in range(4)]
            # An integer proportional to mean net probability avoids floating ties.
            net[condition]=sum(net[r] for r in readers)
        rows.append(dict(key=item['key'],question_id=item['id'],block=item['block'],
            original_split=item['split'],gain=bool(not short and long),outcome=outcome,
            short_correct=short,long_correct=long,
            short_tokens=item['outcomes']['short']['tokens'],long_tokens=item['outcomes']['long']['tokens'],
            probabilities=probabilities,net=net))
    assert len(rows)==57
    short_correct=sum(r['short_correct'] for r in rows)
    long_correct=sum(r['long_correct'] for r in rows)
    short_tokens=sum(r['short_tokens'] for r in rows)
    long_tokens=sum(r['long_tokens'] for r in rows)
    grid={}
    for condition in ['Q','P','q1','q2','p1','p2']:
        grid[condition]=[dict(fraction=f,**allocation(rows,condition,math.floor(f*len(rows))))
                         for f in plan['extension_fractions']]
    q,p=[allocation(rows,c,28) for c in ['Q','P']]
    by_question=defaultdict(list)
    for row in rows:
        by_question[row['question_id']].append(row)
    discordant=[]
    wins=0
    for question,items in by_question.items():
        if len(items)==2 and sum(r['gain'] for r in items)==1:
            gain=next(r for r in items if r['gain'])
            other=next(r for r in items if not r['gain'])
            comparison={}
            for condition in ['Q','P']:
                gap=gain['net'][condition]-other['net'][condition]
                comparison[condition]=dict(gap=gap,strict_win=gap>0,tie=gap==0)
            wins+=comparison['P']['strict_win']
            discordant.append(dict(question_id=question,gain_key=gain['key'],other_key=other['key'],
                                   comparisons=comparison))
    failures=[]
    if p['expected_correct']-q['expected_correct']<2-1e-9:
        failures.append('prefix advantage at 28 extensions is less than two correct answers')
    if p['expected_correct']<long_correct-1e-9:
        failures.append('prefix allocation loses correctness relative to fixed long')
    if p['expected_tokens']>0.85*long_tokens+1e-9:
        failures.append('prefix allocation exceeds 85% fixed-long tokens')
    if p['expected_tokens']>q['expected_tokens']+1e-9:
        failures.append('prefix allocation costs more realized tokens than question-only')
    if wins<3:
        failures.append('prefix strict gain-seed ranking wins fewer than three of four')
    rng=random.Random(157222)
    ids=sorted(by_question)
    differences=[]
    token_differences=[]
    for _ in range(10000):
        sample=[r for i in rng.choices(ids,k=len(ids)) for r in by_question[i]]
        count=math.floor(0.5*len(sample))
        aq,ap=[allocation(sample,c,count) for c in ['Q','P']]
        differences.append((ap['expected_correct']-aq['expected_correct'])/len(sample))
        token_differences.append(ap['expected_tokens']-aq['expected_tokens'])
    differences.sort();token_differences.sort()
    interval=[differences[249],differences[9749]]
    decision='stop_incremental_prefix_branch' if failures else 'inconclusive'
    if not failures and interval[0]>0:
        decision='earn_practical_signal_feasibility_review'
    agreement={}
    for condition,a,b in [('Q','q1','q2'),('P','p1','p2')]:
        unique=rows if condition=='P' else [items[0] for items in by_question.values()]
        first=[r['net'][a]/100 for r in unique];second=[r['net'][b]/100 for r in unique]
        agreement[condition]=dict(instances=len(unique),net_score_pearson=correlation(first,second),
                                  mean_absolute_net_probability_gap=statistics.mean(abs(a-b) for a,b in zip(first,second)))
    natural=[r for r in graded if not r['eligible']]
    early_correct=sum(r['outcomes']['short']['correct'] for r in natural)
    early_tokens=sum(r['outcomes']['short']['tokens'] for r in natural)
    random_grid=[]
    for f in plan['extension_fractions']:
        count=math.floor(f*len(rows));fraction=count/len(rows)
        random_grid.append(dict(extensions=count,expected_correct=short_correct+fraction*(long_correct-short_correct),
            expected_tokens=short_tokens+fraction*(long_tokens-short_tokens)))
    result=dict(decision=decision,failures=failures,eligible=57,questions=30,
        baselines=dict(short_correct=short_correct,long_correct=long_correct,
                       short_tokens=short_tokens,long_tokens=long_tokens),
        primary=dict(Q=q,P=p,correctness_difference=p['expected_correct']-q['expected_correct'],
                     token_difference=p['expected_tokens']-q['expected_tokens']),
        prediction_metrics={c:prediction_metrics(rows,c) for c in ['Q','P','q1','q2','p1','p2']},
        allocation_grid=grid,random_expected_grid=random_grid,reader_agreement=agreement,
        discordant_seed_questions=discordant,strict_prefix_wins=wins,
        paired_question_bootstrap_accuracy_difference_ci95=interval,
        paired_question_bootstrap_token_difference_ci95=[token_differences[249],token_differences[9749]],
        natural_early_answers=dict(instances=len(natural),correct=early_correct,tokens=early_tokens),
        overall60_primary={c:dict(expected_correct=a['expected_correct']+early_correct,
                                 expected_tokens=a['expected_tokens']+early_tokens)
                           for c,a in [('Q',q),('P',p)]},
        note='Eligible 57 are primary. Same count means same planning reserve, not same realized tokens. Original split and all outcomes remain exploratory.')
    (HERE/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'joined-predictions.json').write_text(json.dumps(rows,indent=2)+'\n')
    with (HERE/'allocations.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=['condition','fraction','extensions','expected_correct','expected_tokens','expected_gains_captured','partially_selected_tied_cases'])
        writer.writeheader()
        for condition,items in grid.items():
            writer.writerows(dict(condition=condition,**item) for item in items)
    print(json.dumps({key:result[key] for key in ['decision','failures','primary','strict_prefix_wins',
          'paired_question_bootstrap_accuracy_difference_ci95']},indent=2))


if __name__=='__main__':
    main()
