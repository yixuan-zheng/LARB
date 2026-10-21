"""Reproduce saved client-deadline outcomes, including old cap/wrong/late cases."""
import hashlib
import json
from pathlib import Path
import sys

repo=Path(__file__).resolve().parents[4]
sys.path.insert(0,str(repo/'week3/larb/code'))
sys.path.insert(0,str(repo/'week4/step1/controlled-comparison'))
from baseline import boxed
from grade_stage3 import grade_answer
from metrics import finish_kind, outcome

root=repo/'week3/larb/burst-policy/results/job-6320907'
old=json.loads((root/'analysis/graded.json').read_text())
trace=json.loads((root/'trace.json').read_text())
complete=json.loads((root/'run-complete.json').read_text())
clients={r['key']:r for p in complete['phases'] for r in p['client']}
worker=[json.loads(l) for l in (root/'worker.jsonl').read_text().splitlines()]
caps={e['key']:e['event'] for e in worker if e['event'] in ('thinking_cap','answer_cap')}
mismatches=[];counts={m:dict(correct_on_time=0,completed_correct=0) for m in ['full','arrival','live']}
for expected in old:
    raw=json.loads((root/'requests'/f"{expected['key']}.json").read_text())
    client=clients[expected['key']]
    post=raw['raw_output'].split('</think>',1)[1] if '</think>' in raw['raw_output'] else ''
    grade=grade_answer(raw['reference'],boxed(post))
    result=outcome(grade['correct'],finish_kind(raw,caps.get(expected['key'])),
                   client['client_finished']-client['scheduled'],trace['relative_deadline_seconds'])
    oracle=dict(completed_correct=expected['completed_correct'],correct_on_time=expected['client_correct_on_time'])
    if result!=oracle:
        mismatches.append(dict(key=expected['key'],expected=oracle,actual=result))
    for name in result: counts[expected['policy']][name]+=result[name]
assert len(old)==36
print(json.dumps(dict(passed=not mismatches,records=36,counts=counts,mismatches=mismatches,
    oracle_sha256=hashlib.sha256((root/'analysis/graded.json').read_bytes()).hexdigest(),
    note='Historical saved outcomes only; no new inference or independent accuracy evidence'),indent=2))
assert not mismatches
