"""Cross-block diagnostic fixed-lane estimates, never a causal policy replay."""
import argparse,heapq,json,statistics,csv
from pathlib import Path
from collections import defaultdict
parser=argparse.ArgumentParser();parser.add_argument('--derived',type=Path,default=Path(__file__).resolve().parent/'derived');args=parser.parse_args();D=args.derived;OUT=D/'prediction';OUT.mkdir(exist_ok=False)
def load(p):return json.loads(p.read_text())
def med(v):return statistics.median(v)
def q90(v):return sorted(v)[max(0,int(.9*len(v)+.999)-1)]
def summarize(v):return dict(n=len(v),mean=statistics.mean(v),median=med(v),p90=q90(v),max=max(v)) if v else dict(n=0)
def fifo(now,slots,services):
 slots=list(slots);heapq.heapify(slots);result=[]
 for key,service in services:
  finish=heapq.heappop(slots)+service;result.append((key,now+finish));heapq.heappush(slots,finish)
 return dict(result)
# Fixed-lane logic must reuse lanes: this is the corrected Week5 counterexample.
assert list(fifo(0,[10,90],[(str(i),40) for i in range(5)]).values())==[50,90,130,130,170]
requests={run:{r['key']:r for r in load(D/run/'requests.json')} for run in ['pilot','b0','b1']};summary=[];allvalidation=[];decisions=[];candidateframes=[]
for run in requests:
 trainnames=['b1'] if run=='b0' else ['b0'] if run=='b1' else ['b0','b1']
 train=[r for name in trainnames for r in requests[name].values() if r['role']=='measured' and r['policy'] in ['fixed4k','fixed8k','arrival']]
 # Only timing/token-length calibration, never reference answers or correctness.
 profiles={budget:[r for r in train if r['initial_budget']==budget] for budget in [4096,8192]};tail={budget:[r['answer_tokens_after_close'] for r in rr] for budget,rr in profiles.items()};think={budget:[r['thinking_tokens'] for r in rr] for budget,rr in profiles.items()}
 fallback=med([load(D/name/'extraction-summary.json')['decode_cadence']['2']['median'] for name in trainnames]);prefill=med([max(0,r['first_token']-r['first_active']) for r in train]);bykey=requests[run]
 def remaining(state,tau,newbudget=None):
  t=state['tokens'];budget=state['budget'] if newbudget is None else newbudget
  pp=tail[4096 if budget<=4096 else 8192]
  if state['closed']:
   used=max(0,t-state['close_index']-1);survivors=[n-used for n in pp if n>used];return (med(survivors) if survivors else max(0,2049-used))*tau
  if state['cued']:
   # Cue close offset is12 for the frozen14-token cue; read it from executed data below.
   end=state['cue_start']+close_offset+1+med(pp);return max(0,end-t)*tau
  if newbudget is not None and budget<=t:target=t
  else:
   past=[n for n in think[4096 if budget<=4096 else 8192] if n>t]
   target=min(budget,med(past)) if past else max(t,budget)
  return max(0,target+close_offset+1+med(pp)-t)*tau
 # Same cue in all records; offset is derived from its token contract, not guessed.
 firstroot=(Path(__file__).resolve().parents[4]/'week6/queue-pressure-results/collection-6791535/job-6791535-combined/block0/job-6791535-pilot')
 firstraw=load(next((firstroot/'requests').glob('*.json')));close_offset=firstraw['cue_ids'].index(firstraw['close_id'])
 def estimates(frame,cut=None,multiplier=1):
  tau=frame['tau_online'] or fallback;slots=[remaining(st,tau,4096 if st['key']==cut else None)*multiplier for st in frame['active']]
  services=[]
  for k in frame['waiting']:
   budget=bykey[k]['initial_budget'];services.append((k,(prefill+(med(think[budget])+close_offset+1+med(tail[budget]))*tau)*multiplier))
  return fifo(frame['now'],slots,services)
 validation=[];eligible=[]
 cuts=load(D/run/'cuts.json');cutstepkeys=defaultdict(list)
 for c in cuts:
  if c['role']=='measured':cutstepkeys[c['step']].append(c['key'])
 for frame in load(D/run/'frames.json'):
  if frame['role']!='measured':continue
  base=estimates(frame)
  if frame['policy']!='live':
   for k,pred in base.items():
    actual=bykey[k]['finish'];validation.append(dict(run=run,phase=frame['phase'],step=frame['step'],key=k,predicted_finish=pred,actual_finish=actual,error_seconds=pred-actual,absolute_error_seconds=abs(pred-actual),predicted_timely=pred<=bykey[k]['deadline'],actual_timely=actual<=bykey[k]['deadline'],optimistic_finish=frame['now']+.75*(pred-frame['now']),pessimistic_finish=frame['now']+1.25*(pred-frame['now'])))
  if not frame['eligible']:continue
  base_fast=estimates(frame,multiplier=.75);options=[]
  for k in frame['eligible']:
   pred=estimates(frame,k);slow=estimates(frame,k,1.25)
   gains=[w for w in frame['waiting'] if base[w]>bykey[w]['deadline'] and pred[w]<=bykey[w]['deadline']]
   robust=[w for w in frame['waiting'] if base_fast[w]>bykey[w]['deadline'] and slow[w]<=bykey[w]['deadline']]
   target=next(a for a in frame['active'] if a['key']==k)
   saving=max(0,remaining(target,frame['tau_online'] or fallback)-remaining(target,frame['tau_online'] or fallback,4096))
   options.append(dict(key=k,gains=gains,robust_gains=robust,predicted_release_saving=saving,short_finish=frame['now']+remaining(target,frame['tau_online'] or fallback,4096),tokens=target['tokens']))
  # Pick at most one target, ranking robust rescued waiters first then earliest release.
  best=min(options,key=lambda o:(-len(o['robust_gains']),o['short_finish'],o['key']))
  chosen=best['key'] if best['robust_gains'] else None
  rr=dict(run=run,phase=frame['phase'],policy=frame['policy'],step=frame['step'],eligible=len(frame['eligible']),point_rescue_exists=any(o['gains'] for o in options),robust_rescue_exists=bool(chosen),chosen=chosen,options=options,waiting=frame['waiting'],now=frame['now'])
  eligible.append(rr)
  if frame['step'] in cutstepkeys:
   rr=dict(rr,observed_cuts=cutstepkeys[frame['step']]);decisions.append(rr)
 # Collapse repeated predictions to request-level descriptive medians; frames are not independent observations.
 grouped=defaultdict(list)
 for v in validation:grouped[v['key']].append(v)
 request_errors=[dict(key=k,phase=vv[0]['phase'],states=len(vv),median_abs_error=med([v['absolute_error_seconds'] for v in vv]),median_signed_error=med([v['error_seconds'] for v in vv]),deadline_classification_error_rate=statistics.mean(v['predicted_timely']!=v['actual_timely'] for v in vv),sensitivity_interval_coverage=statistics.mean(v['optimistic_finish']<=v['actual_finish']<=v['pessimistic_finish'] for v in vv)) for k,vv in grouped.items()]
 info=dict(run=run,training_runs=trainnames,timing_profile_rows=len(train),profile_rows_by_budget={str(k):len(v) for k,v in profiles.items()},fallback_tau=fallback,prefill_median=prefill,validation_waiter_requests=len(request_errors),median_abs_error_per_request=summarize([r['median_abs_error'] for r in request_errors]),median_signed_error_per_request=summarize([r['median_signed_error'] for r in request_errors]),mean_request_deadline_classification_error=statistics.mean(r['deadline_classification_error_rate'] for r in request_errors) if request_errors else None,mean_request_sensitivity_interval_coverage=statistics.mean(r['sensitivity_interval_coverage'] for r in request_errors) if request_errors else None,eligible_states=len(eligible),point_rescue_states=sum(r['point_rescue_exists'] for r in eligible),robust_rescue_states=sum(r['robust_rescue_exists'] for r in eligible),important='One-second sampled correlated states; ±25% is a sensitivity bracket, not a calibrated confidence interval. No causal counterfactual accuracy/goodput computed.')
 summary.append(info);allvalidation+=request_errors;candidateframes+=eligible
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(OUT/'validation-by-request.json').write_text(json.dumps(allvalidation,indent=2)+'\n');(OUT/'decision-opportunities.json').write_text(json.dumps(decisions,indent=2)+'\n');(OUT/'eligible-states.json').write_text(json.dumps(candidateframes,indent=2)+'\n')
print(json.dumps(summary,indent=2))
for d in decisions:print('DECISION',d['run'],d['phase'],d['step'],'observed',d['observed_cuts'],'point',d['point_rescue_exists'],'robust',d['chosen'],'options',json.dumps(d['options']))
