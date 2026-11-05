"""Paired outcome accounting and scheduler slot reuse; CPU only, no counterfactual grading."""
import argparse,json,statistics
from collections import Counter,defaultdict
from pathlib import Path
from extract import SOURCES,quant,dump,writecsv
p=argparse.ArgumentParser();p.add_argument('--derived',type=Path,default=Path(__file__).resolve().parent/'derived');a=p.parse_args();D=a.derived
runs={run:json.loads((D/run/'requests.json').read_text()) for run,_ in SOURCES};phases={run:json.loads((D/run/'phases.json').read_text()) for run,_ in SOURCES};cuts=[r for run in runs for r in json.loads((D/run/'cuts.json').read_text()) if r['role']=='measured'];paired=[];ledger=[];releases=[]
for run in ['b0','b1']:
 rr=runs[run];index={(r['phase'],r['id']):r for r in rr}
 for r in rr:
  if r['role']!='measured' or r['policy']!='live':continue
  arrival=index[(r['phase'].replace('-live','-arrival'),r['id'])]
  if r['correct'] and arrival['correct']:
   category='both_correct_live_timely_only' if r['good'] and not arrival['good'] else 'both_correct_arrival_timely_only' if arrival['good'] and not r['good'] else 'both_correct_both_timely' if r['good'] else 'both_correct_both_late'
  elif r['correct']:category='live_correct_only'
  elif arrival['correct']:category='arrival_correct_only'
  else:category='both_incorrect'
  row=dict(run=run,condition=r['phase'].split('-')[0],id=r['id'],seed=r['seed'],category=category,live_correct=r['correct'],arrival_correct=arrival['correct'],live_good=r['good'],arrival_good=arrival['good'],live_normal=r['normal'],arrival_normal=arrival['normal'],direct_live_cut=r['cut_time'] is not None,cut_tokens=r['cut_tokens'],live_thinking=r['thinking_tokens'],arrival_thinking=arrival['thinking_tokens'],live_tokens=r['output_tokens'],arrival_tokens=arrival['output_tokens'],live_queue=r['queue_seconds'],arrival_queue=arrival['queue_seconds'],live_service=r['service_seconds'],arrival_service=arrival['service_seconds'],live_latency=r['latency_seconds'],arrival_latency=arrival['latency_seconds'],live_lateness=r['finish']-r['deadline'],arrival_lateness=arrival['finish']-arrival['deadline'],net_good=int(r['good'])-int(arrival['good']),net_correct=int(r['correct'])-int(arrival['correct']));paired.append(row)
  if row['net_good'] or row['net_correct']:ledger.append(row)
# Reuse is an observed same-step allocation event, not a measure of GPU busy time or exact free memory.
within_horizon={run:defaultdict(lambda:dict(active_slot_seconds=0,waiter_seconds=0,with_waiter_seconds=0,accounted_event_intervals=0,max_interval=0)) for run in runs}
for run,root in SOURCES:
 rows={r['key']:r for r in runs[run]};pp={p['name']:p for p in json.loads((root/'progress.json').read_text())};previous=None
 for line in (root/'scheduler.jsonl').open():
  s=json.loads(line)
  if previous:
   previous_keys=[q['key'] for q in previous['active']]+previous['waiting'];names={k.split('--')[0] for k in previous_keys}
   assert len(names)<=1
   if names:
    name=next(iter(names));phase=pp[name];left=max(previous['monotonic'],phase['epoch']);right=min(s['monotonic'],phase['epoch']+phase['horizon_seconds']);dt=max(0,right-left)
    st=within_horizon[run][name];st['active_slot_seconds']+=dt*len(previous['active']);st['waiter_seconds']+=dt*len(previous['waiting']);st['with_waiter_seconds']+=dt*bool(previous['waiting']);st['accounted_event_intervals']+=1;st['max_interval']=max(st['max_interval'],dt)
   if previous['waiting'] and s['finished']:
    admitted=[k for k in s['new'] if k in previous['waiting']]
    for key in s['finished']:
     r=rows[key]
     if r['role']=='measured':releases.append(dict(run=run,phase=r['phase'],step=s['step'],scheduler_time=s['monotonic'],finished=key,persistent_waiters=len(previous['waiting']),new_prior_waiters_same_step=admitted,scheduled_active=len(s['active']),service_finish_minus_scheduler_event=r['finish']-s['monotonic']))
  previous=s
for run in phases:
 for ph in phases[run]:
  st=within_horizon[run][ph['phase']];ph['within_horizon']=dict(st,request_slot_occupancy_fraction=st['active_slot_seconds']/(2*ph['horizon']),waiting_time_fraction=st['with_waiter_seconds']/ph['horizon'])
pooled=[]
for policy in ['fixed4k','fixed8k','arrival','live']:
 rr=[r for run in ['b0','b1'] for r in runs[run] if r['role']=='measured' and r['policy']==policy];ps=[p for run in ['b0','b1'] for p in phases[run] if p['role']=='measured' and p['policy']==policy]
 pooled.append(dict(policy=policy,n=len(rr),correct=sum(r['correct'] for r in rr),good=sum(r['good'] for r in rr),mean_queue=statistics.mean(r['queue_seconds'] for r in rr),mean_service=statistics.mean(r['service_seconds'] for r in rr),mean_latency=statistics.mean(r['latency_seconds'] for r in rr),thinking=sum(r['thinking_tokens'] for r in rr),answer_after_close=sum(r['answer_tokens_after_close'] for r in rr),output_tokens=sum(r['output_tokens'] for r in rr),caps=sum(not r['normal'] for r in rr),active_slot_seconds_within_horizon=sum(p['within_horizon']['active_slot_seconds'] for p in ps),horizon_seconds=sum(p['horizon'] for p in ps),slot_occupancy_fraction=sum(p['within_horizon']['active_slot_seconds'] for p in ps)/(2*sum(p['horizon'] for p in ps))))
assert len(paired)==40 and sum(r['net_good'] for r in paired)==0 and sum(r['net_correct'] for r in paired)==-3
cutstats=dict(n=len(cuts),cut_to_finish=quant([c['cut_to_finish'] for c in cuts]),cue_to_finish=quant([c['cue_to_finish'] for c in cuts]),cut_to_cue=quant([c['cut_to_cue'] for c in cuts]),remaining_8k_headroom=quant([c['remaining_8k_tokens'] for c in cuts]),headroom_under_1024=sum(c['remaining_8k_tokens']<1024 for c in cuts),zero_progress=sum(c['tokens_at_cut']==0 for c in cuts),next_waiter_uses_other_lane=sum(not c['donor_finished_before_next_waiter'] for c in cuts),not_causal='Cut targets and queue events are correlated; no individual intervention effect is identified.')
summary=dict(coverage=dict(all_records=sum(len(r) for r in runs.values()),measured_records=sum(r['role']=='measured' for rr in runs.values() for r in rr),probe_records=sum(r['role']=='probe' for rr in runs.values() for r in rr),runs=len(runs),paired_current_rows=len(paired)),paired_categories=dict(Counter(r['category'] for r in paired)),ledger=ledger,pooled=pooled,cuts=cutstats,reuse=dict(queued_release_observations=len(releases),release_steps=len({(r['run'],r['step']) for r in releases}),same_step_release_steps=len({(r['run'],r['step']) for r in releases if r['new_prior_waiters_same_step']}),same_step_reuse=sum(bool(r['new_prior_waiters_same_step']) for r in releases),by_run={run:dict(n=sum(r['run']==run for r in releases),same_step=sum(r['run']==run and bool(r['new_prior_waiters_same_step']) for r in releases)) for run in runs}),predictor=json.loads((D/'prediction/summary.json').read_text()),limits=['No GPU execution-utilization measurement','No exact KV reclamation timing or global free-block trace','Fixed two-sequence cap, not a demonstrated physical GPU capacity limit','Slot-time intervals reconstruct scheduler state; not kernel-time profiling','Cross-block timing profiles reuse development questions; not fresh predictive validation','Single-cut FIFO estimates omit future admissions and coupled intervention cascades','No counterfactual hybrid accuracy or causal per-cut goodput computed'])
dump(D/'audit-summary.json',summary);dump(D/'paired-outcomes.json',paired);writecsv(D/'paired-outcomes.csv',paired);dump(D/'goodput-ledger.json',ledger);dump(D/'release-reuse.json',releases);dump(D/'phases-with-horizon.json',phases)
print(json.dumps(summary,indent=2))
