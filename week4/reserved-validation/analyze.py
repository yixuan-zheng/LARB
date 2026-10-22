"""Grade a complete reserved job, then summarize only a complete six-job campaign."""
import argparse
from collections import Counter,defaultdict
import importlib.metadata as metadata
import json
from pathlib import Path
import random
import statistics
import sys
from execution import digest
from validate import validate

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO/'week3/larb/code'))
sys.path.insert(0,str(REPO/'week4/step1/controlled-comparison'))
from baseline import boxed
from grade_stage3 import grade_answer
from metrics import finish_kind,outcome,summarize


def grade(root):
    assert metadata.version('math-verify')=='0.9.0'
    audit=validate(root)
    complete=json.loads((root/'run-complete.json').read_text());trace=json.loads((root/'trace.json').read_text())
    problems=json.loads((root/'problems100.json').read_text());mechanics={r['key']:r for r in audit['rows']}
    rows=[]
    for phase in complete['phases'][1:]:
        for client in phase['client']:
            key=client['key'];m=mechanics[key];raw=json.loads((root/'requests'/f'{key}.json').read_text())
            post=raw['raw_output'].split('</think>',1)[1] if '</think>' in raw['raw_output'] else ''
            extracted=boxed(post);g=grade_answer(str(problems[client['index']]['answer']),extracted)
            finish=finish_kind(raw,m['cap']);elapsed=client['client_finished']-client['scheduled']
            ids=raw['token_ids'];cue=m['cue_start'];close=m['close_index']
            rows.append(dict(**m,shard=audit['shard'],condition=audit['condition'],finish=finish,
                grading=g,extracted_answer=extracted,reference=str(problems[client['index']]['answer']),
                client_completion_seconds=elapsed,injection_lag_ms=client['injection_lag_ms'],
                thinking_tokens=cue if cue is not None else close if close is not None else len(ids),
                cue_tokens=len(raw['cue_ids']) if cue is not None else 0,output_tokens=len(ids),
                answer_tokens=len(ids)-cue-len(raw['cue_ids']) if cue is not None else len(ids)-close-1 if close is not None else 0,
                **outcome(g['correct'],finish,elapsed,trace['relative_deadline_seconds'])))
    indexed={(r['block'],r['policy'],r['index']):r for r in rows}
    pairs=[]
    for b in [0,1]:
        for i in sorted({r['index'] for r in rows}):
            a,l=indexed[b,'admission',i],indexed[b,'live',i]
            pairs.append(dict(block=b,index=i,deadline_delta=int(l['correct_on_time'])-int(a['correct_on_time']),
                correctness_delta=int(l['completed_correct'])-int(a['completed_correct']),
                admission_key=a['key'],live_key=l['key'],initial_budget_match=a['initial_budget']==l['initial_budget']))
    summaries=[dict(policy=p,**summarize([r for r in rows if r['policy']==p],2*trace['observation_horizon_seconds'])) for p in ['admission','live']]
    result=dict(complete=True,validation_passed=True,shard=audit['shard'],condition=audit['condition'],
        unique_questions=12,measured_outcomes=48,summary=summaries,paired=pairs,
        audit={k:v for k,v in audit.items() if k!='rows'},input_hashes={n:digest(root/n) for n in ['plan.json','trace.json','manifest.json']},
        analysis_sources={str(p.relative_to(REPO)):digest(p) for p in [Path(__file__),Path(__file__).with_name('validate.py'),REPO/'week3/larb/code/grade_stage3.py',REPO/'week3/larb/code/baseline.py']},
        grading_versions={n:metadata.version(n) for n in ['math-verify','sympy','latex2sympy2_extended']})
    out=root/'analysis';out.mkdir(exist_ok=True)
    for n,d in [('summary.json',result),('graded.json',rows),('review-queue.json',[r for r in rows if r['grading']['issue'] or not r['completed_correct']])]:
        (out/n).write_text(json.dumps(d,indent=2)+'\n')
    return result


def aggregate(roots,out):
    results=[json.loads((r/'analysis/summary.json').read_text()) for r in roots]
    assert len(results)==6 and {(r['condition'],r['shard']) for r in results}=={(c,s) for c in ['low_load','late_burst','sustained_pressure'] for s in [0,1]}
    assert len({r['input_hashes']['plan.json'] for r in results})==1
    assert all(r['complete'] and r['validation_passed'] for r in results)
    rows=[v for root in roots for v in json.loads((root/'analysis/graded.json').read_text())]
    assert len(rows)==288 and len({r['index'] for r in rows})==24
    policies=['admission','live'];conditions=['low_load','late_burst','sustained_pressure']
    totals=[];deltas={};block_quality={};block_deadline={}
    for c in conditions:
        for p in policies:
            group=[r for r in rows if r['condition']==c and r['policy']==p]
            assert len(group)==48
            totals.append(dict(condition=c,policy=p,n=48,correct_on_time=sum(r['correct_on_time'] for r in group),
                completed_correct=sum(r['completed_correct'] for r in group),
                median_client_seconds=statistics.median(r['client_completion_seconds'] for r in group),
                failures=dict(Counter(r['finish'] for r in group if r['finish']!='normal')),
                binding_live_cutoffs=sum(r['binding_live_cutoff'] for r in group)))
        get=lambda p,k:next(r[k] for r in totals if r['condition']==c and r['policy']==p)
        deltas[c]=get('live','correct_on_time')-get('admission','correct_on_time')
        for b in [0,1]:
            grouped={p:[r for r in rows if (r['condition'],r['block'],r['policy'])==(c,b,p)] for p in policies}
            block_quality[f'{c}/b{b}']=sum(r['completed_correct'] for r in grouped['live'])-sum(r['completed_correct'] for r in grouped['admission'])
            block_deadline[f'{c}/b{b}']=sum(r['correct_on_time'] for r in grouped['live'])-sum(r['correct_on_time'] for r in grouped['admission'])
    quality=(sum(r['completed_correct'] for r in rows if r['policy']=='live')-sum(r['completed_correct'] for r in rows if r['policy']=='admission'))/144
    pressure=sum(deltas[c] for c in conditions[1:])/96
    index={(r['condition'],r['block'],r['policy'],r['index']):r for r in rows}
    per_question=[]
    for i in sorted({r['index'] for r in rows}):
        contrasts=[int(index[c,b,'live',i]['correct_on_time'])-int(index[c,b,'admission',i]['correct_on_time']) for c in conditions[1:] for b in [0,1]]
        per_question.append(dict(index=i,mean_pressure_deadline_difference=statistics.mean(contrasts)))
    rng=random.Random(622205);values=[r['mean_pressure_deadline_difference'] for r in per_question]
    draws=sorted(statistics.mean(rng.choices(values,k=24)) for _ in range(10000))
    screen=dict(positive_pooled_pressure=pressure>0,neither_pressure_condition_negative=all(deltas[c]>=0 for c in conditions[1:]),
        quality_within_observed_tolerance=quality>=-.03,condition_block_quality_losses_bounded=all(v>=-1 for v in block_quality.values()),
        low_load_deadline_guard=all(block_deadline[f'low_load/b{b}']>=-1 for b in [0,1]),
        binding_both_pressure_conditions=all(any(r['binding_live_cutoff'] for r in rows if r['policy']=='live' and r['condition']==c) for c in conditions[1:]))
    report=dict(complete=True,measured_outcomes=288,unique_questions=24,per_condition=totals,deadline_count_deltas=deltas,
        primary_pressure_success_fraction_difference=pressure,eventual_correctness_difference=quality,
        condition_block_correctness_deltas=block_quality,condition_block_deadline_deltas=block_deadline,
        continuation_screen=screen,screen_passed=all(screen.values()),
        descriptive_bootstrap=dict(resamples=10000,seed=622205,unit='question, repeated observations together',
             sensitivity_interval=[draws[249],draws[9749]],limitation='Conditional sensitivity only; queue coupling/two shards do not support general serving-population confidence'),
        per_question=per_question,
        run_summaries=[dict(root=str(root.relative_to(REPO)),sha256=digest(root/'analysis/summary.json')) for root in roots],
        goodput='Use each saved job/policy summary horizon; no pooled rate across differently calibrated jobs.')
    out.mkdir(exist_ok=True,parents=True);(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path);ap.add_argument('--aggregate',type=Path,nargs='+');ap.add_argument('--out',type=Path);args=ap.parse_args()
    result=aggregate(args.aggregate,args.out) if args.aggregate else grade(args.root)
    print(json.dumps({k:v for k,v in result.items() if k not in ['paired','analysis_sources']},indent=2))
