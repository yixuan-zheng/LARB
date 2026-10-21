"""Provisional scoring of one fully completed block; never a complete-run claim."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

here=Path(__file__).resolve();repo=here.parents[4]
sys.path.insert(0,str(repo/'week3/larb/code'));sys.path.insert(0,str(here.parents[1]))
from baseline import boxed
from grade_stage3 import grade_answer
from metrics import finish_kind,outcome,summarize

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
checkpoint=json.loads((root/'checkpoint.json').read_text())
assert checkpoint['matched_block_complete'] and not checkpoint['overall_comparison_complete']
assert all(hashlib.sha256((root/n).read_bytes()).hexdigest()==sha for n,sha in checkpoint['sha256'].items())
phases=json.loads((root/'phases.json').read_text());trace=json.loads((root/'trace.json').read_text());problems=json.loads((root/'problems100.json').read_text())
worker=json.loads((root/'worker-events.json').read_text());caps={e['key']:e['event'] for e in worker if e['event'] in ('thinking_cap','answer_cap')}
rows=[]
for phase in phases:
    for client in phase['client']:
        path=root/'requests'/f"{client['key']}.json";raw=json.loads(path.read_text()) if path.exists() else None
        if raw:
            assert raw['seed']==6222+client['index'] and raw['tokens']==client['tokens']
        post=raw['raw_output'].split('</think>',1)[1] if raw and '</think>' in raw['raw_output'] else ''
        grade=grade_answer(str(problems[client['index']]['answer']),boxed(post))
        finish=finish_kind(raw,caps.get(client['key'])) if client['status']=='terminal' else client['status']
        elapsed=client['client_finished']-client['scheduled'] if 'client_finished' in client else None
        events=[e for e in worker if e.get('key')==client['key']]
        reductions=[e for e in events if e['event']=='live_reduction'];cues=[e for e in events if e['event']=='cue_started']
        binding=any(c['monotonic']>=r['monotonic'] and c['tokens']>=r['budget'] for r in reductions for c in cues)
        rows.append(dict(policy=phase['policy'],index=client['index'],key=client['key'],finish=finish,
            grading=grade,client_completion_seconds=elapsed,live_reduction=bool(reductions),binding_live_cutoff=binding,
            thinking_tokens=None,answer_tokens=None,**outcome(grade['correct'],finish,elapsed,trace['relative_deadline_seconds'])))
assert len(rows)==48
summary=[dict(policy=mode,**summarize([r for r in rows if r['policy']==mode],trace['observation_horizon_seconds'])) for mode in ['full','arrival','admission','live']]
result=dict(provisional=True,overall_comparison_complete=False,block=checkpoint['block'],unique_problems=12,
            summary=summary,rows=rows,parser_issues=[r['key'] for r in rows if r['grading']['issue']])
(root/'preview.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
