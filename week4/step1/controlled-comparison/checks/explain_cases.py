"""Reconstruct paired cases from a fully validated comparison, without tuning."""
import argparse
import hashlib
import json
from pathlib import Path

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
summary=json.loads((root/'analysis/summary.json').read_text());assert summary['complete'] and summary['validation_passed']
rows=json.loads((root/'analysis/graded.json').read_text());indexed={(r['block'],r['policy'],r['index']):r for r in rows}
worker=[json.loads(l) for l in (root/'worker.jsonl').read_text().splitlines()]
scheduler=[json.loads(l) for l in (root/'scheduler.jsonl').read_text().splitlines()]
admissions={e['key']:e for e in scheduler if e['event']=='admission_decision'}

def record(block,mode,index):
    path=root/'requests'/f'b{block}-{mode}-{index:02d}.json'
    return json.loads(path.read_text())

def common_prefix(a,b,limit):
    return next((i for i in range(limit) if a[i]!=b[i]),limit)

blocks=[]
for block in [0,1]:
    epochs={mode:min(record(block,mode,i)['received'] for i in range(12)) for mode in ['admission','live']}
    rescues=[];quality=[]
    for i in range(12):
        a,l=indexed[block,'admission',i],indexed[block,'live',i]
        pair={mode:record(block,mode,i) for mode in ['admission','live']}
        if l['correct_on_time']!=a['correct_on_time']:
            rescues.append(dict(index=i,deadline_delta=int(l['correct_on_time'])-int(a['correct_on_time']),
                both_eventually_correct=a['completed_correct'] and l['completed_correct'],
                client_completion_seconds={mode:indexed[block,mode,i]['client_completion_seconds'] for mode in pair},
                admitted_server_offset_seconds={mode:admissions[pair[mode]['key']]['monotonic']-epochs[mode] for mode in pair},
                final_server_offset_seconds={mode:pair[mode]['monotonic']-epochs[mode] for mode in pair}))
        if l['completed_correct']!=a['completed_correct']:
            left,right=pair['admission']['token_ids'],pair['live']['token_ids']
            limit=min(len(left),len(right),2048)
            quality.append(dict(index=i,correctness_delta=int(l['completed_correct'])-int(a['completed_correct']),
                extracted_answers={mode:indexed[block,mode,i]['extracted_answer'] for mode in pair},
                initial_budgets={mode:indexed[block,mode,i]['initial_budget'] for mode in pair},
                own_binding_live_cutoff=l['binding_live_cutoff'],common_prefix_tokens=common_prefix(left,right,limit),
                compared_prefix_tokens=limit,
                interpretation='Equal seeds do not guarantee equal sampled outputs under changed batching; a quality gain without an own live cutoff is not direct evidence of improved reasoning.'))
    pivot=1;live=record(block,'live',pivot);adm=record(block,'admission',pivot)
    updates=[e for e in worker if e.get('key')==live['key'] and e['event']=='live_reduction']
    cues=[e for e in worker if e.get('key')==live['key'] and e['event']=='cue_started']
    limit=min(2048,len(live['token_ids']),len(adm['token_ids']))
    next_admit=min((e for e in admissions.values() if e['key'].startswith(f'b{block}-live-') and
                    e['monotonic']>=live['monotonic']),key=lambda e:e['monotonic'],default=None)
    pivot_case=dict(index=pivot,matched_prefix_tokens=common_prefix(adm['token_ids'],live['token_ids'],limit),
        compared_prefix_tokens=limit,live_reduction_tokens=[e['tokens'] for e in updates],
        live_cue_start_tokens=[e['tokens'] for e in cues],
        final_server_offset_seconds=dict(admission=adm['monotonic']-epochs['admission'],live=live['monotonic']-epochs['live']),
        next_live_admission_after_pivot_final=next_admit,
        interpretation='Event ordering is consistent with capacity release helping queued work. Other generated trajectories also change; do not attribute every timing difference to the cue alone.')
    blocks.append(dict(block=block,pivot=pivot_case,deadline_changes=rescues,quality_changes=quality))
result=dict(blocks=blocks,unique_deadline_gain_problems=sorted({r['index'] for b in blocks for r in b['deadline_changes'] if r['deadline_delta']>0}),
    unique_deadline_loss_problems=sorted({r['index'] for b in blocks for r in b['deadline_changes'] if r['deadline_delta']<0}),
    unique_quality_gain_problems=sorted({r['index'] for b in blocks for r in b['quality_changes'] if r['correctness_delta']>0}),
    unique_quality_loss_problems=sorted({r['index'] for b in blocks for r in b['quality_changes'] if r['correctness_delta']<0}),
    source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(root/'analysis/cases.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
