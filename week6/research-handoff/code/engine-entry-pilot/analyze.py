"""CPU grading: common horizon, scheduled arrivals, capped/missing outcomes retained."""
import argparse,json,statistics,sys
from pathlib import Path
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'aime-budget-screen'))
from common import extract_integer

def completion(raw,cue_start=None):
 ids=raw['token_ids'];close=raw['close_id'];eos=raw['eos_id'];cue=raw['cue_ids'];closes=[i for i,t in enumerate(ids) if t==close]
 if not raw['complete'] or not ids or ids[-1]!=eos or len(closes)!=1:return dict(normal=False,reason='incomplete_or_bad_close')
 at=closes[0]
 if cue_start is not None and ids[cue_start:cue_start+len(cue)]!=cue:raise ValueError('Realized cue mismatch')
 # Preserve legacy answer-cap semantics, including trailing cue tokens.
 capped=len(ids)-at-1>2048
 return dict(normal=not capped,reason='answer_cap' if capped else 'normal',close_index=at,cue_start=cue_start)

def analyze(root):
 progress=json.loads((root/'progress.json').read_text());worker=[]
 if (root/'probe-plan.json').exists():
  seen={p['name'] for p in progress}
  for p in json.loads((root/'probe-plan.json').read_text()):
   if p['name'] not in seen:progress.append(dict(**p,epoch=None,client=[],complete=False))
 if (root/'trace.json').exists():
  trace=json.loads((root/'trace.json').read_text());seen={p['name'] for p in progress}
  for c in trace['conditions']:
   for policy in c['policy_order']:
    name=c['name']+'-'+policy
    if name not in seen:progress.append(dict(name=name,policy=policy,epoch=None,horizon_seconds=c['horizon_seconds'],arrivals=c['arrivals'],client=[],complete=False))
 if (root/'worker.jsonl').exists():
  for line in (root/'worker.jsonl').read_text().splitlines():
   try:worker.append(json.loads(line))
   except json.JSONDecodeError:pass
 cues={v['key']:v['tokens'] for v in worker if v['event']=='cue_started'};reductions=[v for v in worker if v['event']=='live_reduction'];rows=[];summary=[]
 for phase in progress:
  clients={v['key']:v for v in phase['client']};rr=[]
  for item in phase['arrivals']:
   key=f"{phase['name']}--r{item['slot']:02d}";p=root/'requests'/(key+'.json');raw=json.loads(p.read_text()) if p.exists() else None;client=clients.get(key);audit=completion(raw,cues.get(key)) if raw else dict(normal=False,reason='missing');grade=extract_integer(raw['raw_output']) if raw else dict(value=None,issue='missing')
   correct=bool(raw and audit['normal'] and grade['value']==raw['reference']);finish=raw['finished'] if raw else None;deadline=phase['epoch']+item['offset_seconds']+item['relative_deadline_seconds'] if phase['epoch'] is not None else None;timely=bool(finish is not None and deadline is not None and finish<=deadline and finish<=phase['epoch']+phase['horizon_seconds']);latency=finish-(phase['epoch']+item['offset_seconds']) if finish is not None and phase['epoch'] is not None else None
   row=dict(role=phase.get('role','measured'),phase=phase['name'],policy=phase['policy'],key=key,id=item['id'],seed=item['seed'],present=raw is not None,complete=bool(raw and raw['complete']),correct=correct,timely=timely,good=correct and timely,deadline=deadline,finish=finish,latency_seconds=latency,output_tokens=len(raw['token_ids']) if raw else 0,issue=grade['issue'],**audit);rows.append(row);rr.append(row)
  latency=[v['latency_seconds'] for v in rr if v['latency_seconds'] is not None];latency.sort();n=len(rr);h=phase['horizon_seconds'];summary.append(dict(role=phase.get('role','measured'),phase=phase['name'],policy=phase['policy'],planned=n,present=sum(v['present'] for v in rr),correct=sum(v['correct'] for v in rr),correct_on_time=sum(v['good'] for v in rr),goodput_per_minute=60*sum(v['good'] for v in rr)/h,deadline_misses=sum(not v['timely'] for v in rr),horizon_seconds=h,mean_latency=statistics.mean(latency) if latency else None,max_latency=max(latency) if latency else None,p95_latency=latency[max(0,int(.95*len(latency)+.999)-1)] if latency else None,total_output_tokens=sum(v['output_tokens'] for v in rr),interventions=sum(v['key'].startswith(phase['name']+'--') for v in reductions),injection_valid=phase.get('injection_valid',False),fully_drained=phase['complete']))
 result=dict(summary=summary,planned=sum(v['planned'] for v in summary),planned_measured=sum(v['planned'] for v in summary if v['role']=='measured'),planned_probes=sum(v['planned'] for v in summary if v['role']=='probe'),rows=rows,caution='Small paired development pilot; no tail-population or model-generalization claim. Missing/capped rows remain failures. Incomplete phases are not valid matched policy comparisons. Review all wrong/ambiguous extraction before accuracy interpretation.')
 (root/'summary.json').write_text(json.dumps(result,indent=2)+'\n');(root/'review-queue.json').write_text(json.dumps([v for v in rows if v['issue'] or not v['correct']],indent=2)+'\n');print(json.dumps(summary,indent=2));return result
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);analyze(p.parse_args().root)
