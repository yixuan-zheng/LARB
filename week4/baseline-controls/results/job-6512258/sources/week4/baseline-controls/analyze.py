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
    summaries=[dict(policy=p,**summarize([r for r in rows if r['policy']==p],2*trace['observation_horizon_seconds'])) for p in ['fixed2048','fixed4096','admission','live']]
    result=dict(complete=True,validation_passed=True,shard=audit['shard'],condition=audit['condition'],
        unique_questions=len({r['index'] for r in rows}),measured_outcomes=len(rows),summary=summaries,paired=pairs,
        audit={k:v for k,v in audit.items() if k!='rows'},input_hashes={n:digest(root/n) for n in ['plan.json','trace.json','manifest.json']},
        analysis_sources={str(p.relative_to(REPO)):digest(p) for p in [Path(__file__),Path(__file__).with_name('validate.py'),REPO/'week3/larb/code/grade_stage3.py',REPO/'week3/larb/code/baseline.py']},
        grading_versions={n:metadata.version(n) for n in ['math-verify','sympy','latex2sympy2_extended']})
    out=root/'analysis';out.mkdir(exist_ok=True)
    for n,d in [('summary.json',result),('graded.json',rows),('review-queue.json',[r for r in rows if r['grading']['issue'] or not r['completed_correct']])]:
        (out/n).write_text(json.dumps(d,indent=2)+'\n')
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();r=grade(args.root);print(json.dumps(r['summary'],indent=2))
