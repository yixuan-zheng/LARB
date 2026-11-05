"""CPU-only bottleneck reconstruction from preserved immutable serving evidence."""
import argparse,bisect,csv,hashlib,json,statistics
from collections import Counter,defaultdict,deque
from pathlib import Path
REPO=Path(__file__).resolve().parents[4]
SOURCES=[('pilot',REPO/'week6/queue-pressure-results/collection-6777256/job-6777256-pilot'),('b0',REPO/'week6/queue-pressure-results/collection-6791535/job-6791535-combined/block0/job-6791535-pilot'),('b1',REPO/'week6/queue-pressure-results/collection-6791535/job-6791535-combined/block1/job-6791535-pilot')]
def load(p):return json.loads(p.read_text())
def quant(xs):
 xs=sorted(xs)
 return dict(n=len(xs),min=min(xs),median=statistics.median(xs),mean=statistics.mean(xs),p90=xs[max(0,int(.9*len(xs)+.999)-1)],max=max(xs)) if xs else dict(n=0)
def dump(p,x):p.write_text(json.dumps(x,indent=2)+'\n')
def writecsv(p,rows):
 if not rows:return
 with p.open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]),lineterminator='\n');w.writeheader();w.writerows(rows)
def extract(label,root,out):
 progress=load(root/'progress.json');phase={p['name']:p for p in progress};worker=[json.loads(l) for l in (root/'worker.jsonl').read_text().splitlines()];events=defaultdict(dict)
 for e in worker:
  if 'key' in e:
   assert e['event'] not in events[e['key']],(label,e)
   events[e['key']][e['event']]=e
 summary=load(root/'summary.json');rows={r['key']:dict(r) for r in summary['rows']};raws={p.stem:load(p) for p in (root/'requests').glob('*.json')};requests={};cuts=[]
 for key,r in rows.items():
  raw=raws[key];p=phase[r['phase']];item=next(i for i in p['arrivals'] if key.endswith(f"--r{i['slot']:02d}"));ev=events[key];cue=ev.get('cue_started');close=ev.get('thinking_closed');close_index=raw['token_ids'].index(raw['close_id']);assert raw['complete'] and not raw['error'] and raw['token_ids'][-1]==raw['eos_id'] and raw['token_ids'].count(raw['close_id'])==1 and len(raw['token_ids'])-close_index-1<=2049;cut=ev.get('live_reduction')
  requests[key]=dict(r);requests[key].update(run=label,scheduled=p['epoch']+item['offset_seconds'],received=raw['received'],first_token=raw['first_token'],worker_admitted=ev['admitted']['monotonic'],initial_budget=raw['initial_budget'],waiting_at_arrival=raw['waiting_at_arrival'],prompt_tokens=len(raw['prompt_token_ids']),cue_tokens=len(raw['cue_ids']),close_index=close_index,thinking_tokens=cue['tokens'] if cue else close_index,answer_tokens_after_close=len(raw['token_ids'])-close_index-1,cue_time=cue['monotonic'] if cue else None,close_observed_time=close['monotonic'] if close else None,cut_time=cut['monotonic'] if cut else None,cut_tokens=cut['tokens'] if cut else None,first_active=None,last_active=None,scheduler_finished=None,scheduler_finish_step=None,last_computed=None)
 first_active={};finished={};cut_steps={e['pressure_step'] for e in worker if e['event']=='live_reduction'};snapshots={};frames=[];lastsample=defaultdict(lambda:-1e100);recent=deque();last=None;rates=[];stats=defaultdict(lambda:dict(step_count=0,preemptions=0,max_active=0,max_waiting=0,max_observed_block_ids_per_request=0));phase_intervals=defaultdict(lambda:defaultdict(float));first_wait=defaultdict(dict);active_after_finish={};last_event=None
 for line in (root/'scheduler.jsonl').open():
  s=json.loads(line);now=s['monotonic'];active={a['key']:a for a in s['active']};keys=set(active)|set(s['waiting']);names={k.split('--')[0] for k in keys};name=next(iter(names)) if len(names)==1 else None
  assert len(names)<=1
  if last:
   dt=now-last['monotonic'];assert dt>=0
   # Only carry a state over the next event while the same phase is still active.
   # Do not bridge drained phases or startup pauses.
   prevkeys=[a['key'] for a in last['active']]+last['waiting'];prevnames={k.split('--')[0] for k in prevkeys}
   if name is not None and prevnames=={name}:
    phase_intervals[name]['observed_seconds']+=dt
    phase_intervals[name]['active_slot_seconds']+=dt*len(last['active'])
    phase_intervals[name]['waiting_request_seconds']+=dt*len(last['waiting'])
    phase_intervals[name]['with_waiters_seconds']+=dt*bool(last['waiting'])
    phase_intervals[name]['max_interval_seconds']=max(phase_intervals[name]['max_interval_seconds'],dt)
   prev={a['key']:a for a in last['active']}
   if set(prev)==set(active) and 0<len(active)<=2 and all(a['computed_after']-prev[k]['computed_after']==1 for k,a in active.items()):
    # Decode cadence known before the current model execution. Clamp nothing; report outliers.
    rates.append(dict(run=label,phase=name,occupancy=len(active),seconds_per_token=dt));recent.append((now,dt,len(active)))
  while recent and recent[0][0]<now-5:recent.popleft()
  for key,a in active.items():
   if key not in first_active:first_active[key]=(now,s['step'])
   r=requests[key];r['first_active']=first_active[key][0];r['last_active']=now;r['last_computed']=a['computed_after']
   assert a['preemptions']==0
   if name:
    st=stats[name];st['preemptions']=max(st['preemptions'],a['preemptions'])
    if 'blocks' in a:st['max_observed_block_ids_per_request']=max(st['max_observed_block_ids_per_request'],sum(len(g) for g in a['blocks']))
  for key in s['finished']:
   assert key not in finished,(label,key);finished[key]=(now,s['step']);requests[key]['scheduler_finished']=now;requests[key]['scheduler_finish_step']=s['step']
  for key in s['waiting']:first_wait[key].setdefault('at',now)
  if name:
   stats[name]['step_count']+=1;stats[name]['max_active']=max(stats[name]['max_active'],len(active));stats[name]['max_waiting']=max(stats[name]['max_waiting'],len(s['waiting']))
  if s['step'] in cut_steps:snapshots[s['step']]=s
  if name and s['waiting'] and (now-lastsample[name]>=1 or s['step'] in cut_steps or s['new']):
   state=[]
   for key,a in active.items():
    r=requests[key];e=events[key];tokens=max(0,a['computed_after']-r['prompt_tokens']);closed=tokens>r['close_index'];cue=e.get('cue_started');cued=bool(cue and (cue['monotonic']<=now or tokens>cue['tokens']));cut=e.get('live_reduction');budget=4096 if cut and cut['monotonic']<=now else r['initial_budget']
    state.append(dict(key=key,tokens=tokens,closed=closed,cued=cued,budget=budget,cue_start=cue['tokens'] if cued else None,close_index=r['close_index'] if closed else None,initial_budget=r['initial_budget']))
   eligible=[r['key'] for r in state if not r['closed'] and not r['cued'] and r['budget']>4096]
   tau=statistics.median([d for t,d,n in recent if n==len(active)]) if recent and any(n==len(active) for t,d,n in recent) else None
   frames.append(dict(run=label,phase=name,policy=phase[name]['policy'],role=phase[name].get('role','measured'),step=s['step'],now=now,active=state,waiting=s['waiting'],eligible=eligible,tau_online=tau))
   lastsample[name]=now
  last=s
 # A waiting request should have a scheduler first-active event and a terminal record.
 assert set(first_active)==set(rows)==set(finished),(label,len(first_active),len(rows),len(finished))
 for key,r in requests.items():
  assert r['first_active']<=r['first_token']<=r['finish'] and r['scheduler_finished']>=r['last_active']
  r['queue_seconds']=r['first_active']-r['received'];r['service_seconds']=r['finish']-r['first_active'];r['scheduler_release_lag_seconds']=r['scheduler_finished']-r['finish'];r['cue_to_finish_seconds']=r['finish']-r['cue_time'] if r['cue_time'] else None;r['close_to_finish_seconds']=r['finish']-r['close_observed_time'] if r['close_observed_time'] else None
 for e in [e for e in worker if e['event']=='live_reduction']:
  key=e['key'];r=requests[key];snap=snapshots[e['pressure_step']];assert next(a['computed_after'] for a in snap['active'] if a['key']==key)-r['prompt_tokens']==e['tokens']
  assert r['cue_time']>=e['monotonic'] and r['close_observed_time']>=r['cue_time']
  next_waiter=min((requests[w] for w in e['waiting']),key=lambda w:w['first_active']);head=requests[e['waiting'][0]]
  next_time=next_waiter['first_active'];pre_closing=[q for q in requests.values() if q['phase']==r['phase'] and e['monotonic']<=q['scheduler_finished']<=next_time+1e-6]
  c=dict(run=label,key=key,role=r['role'],phase=r['phase'],id=r['id'],step=e['pressure_step'],cut_time=e['monotonic'],tokens_at_cut=e['tokens'],remaining_8k_tokens=max(0,8192-max(4096,e['tokens'])),cut_to_cue=r['cue_time']-e['monotonic'],cue_to_close=r['close_observed_time']-r['cue_time'],close_to_finish=r['finish']-r['close_observed_time'],cue_to_finish=r['finish']-r['cue_time'],cut_to_finish=r['finish']-e['monotonic'],scheduler_release_lag=r['scheduler_finished']-r['finish'],head_waiter=head['key'],head_waiter_deadline_slack=head['deadline']-e['monotonic'],next_waiter=next_waiter['key'],next_waiter_delay=next_time-e['monotonic'],donor_finished_before_next_waiter=r['scheduler_finished']<=next_time+1e-6,releases_before_next_waiter=[q['key'] for q in pre_closing],waiting=list(e['waiting']),raw_correct=r['correct'],raw_good=r['good'])
  cuts.append(c)
 out.mkdir(parents=True,exist_ok=True);dump(out/'requests.json',list(requests.values()));dump(out/'cuts.json',cuts);dump(out/'frames.json',frames);writecsv(out/'requests.csv',[{k:v for k,v in r.items() if k!='waiting_at_arrival'} for r in requests.values()]);writecsv(out/'cuts.csv',cuts)
 rate_summary={str(occ):quant([r['seconds_per_token'] for r in rates if r['occupancy']==occ]) for occ in [1,2]}
 phases=[]
 for p in progress:
  rr=[r for r in requests.values() if r['phase']==p['name']];phases.append(dict(run=label,phase=p['name'],role=p.get('role','measured'),policy=p['policy'],n=len(rr),epoch=p['epoch'],horizon=p['horizon_seconds'],phase_actual_seconds=p['drained_at']-p['epoch'],correct=sum(r['correct'] for r in rr),good=sum(r['good'] for r in rr),caps=sum(not r['normal'] for r in rr),output_tokens=sum(r['output_tokens'] for r in rr),thinking_tokens=sum(r['thinking_tokens'] for r in rr),answer_tokens=sum(r['answer_tokens_after_close'] for r in rr),mean_queue=statistics.mean(r['queue_seconds'] for r in rr),mean_service=statistics.mean(r['service_seconds'] for r in rr),mean_latency=statistics.mean(r['latency_seconds'] for r in rr),**stats[p['name']],**phase_intervals[p['name']]))
 dump(out/'phases.json',phases)
 # Input evidence hashes include large logs but never alter them.
 hashes={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in ['manifest.json','source-lock.json','trace.json','progress.json','worker.jsonl','scheduler.jsonl','summary.json']}
 info=dict(run=label,request_count=len(requests),measured=sum(r['role']=='measured' for r in requests.values()),probe=sum(r['role']=='probe' for r in requests.values()),input_hashes=hashes,decode_cadence=rate_summary,measured_cuts=quant([c['cut_to_finish'] for c in cuts if c['role']=='measured']),measured_cue_tail=quant([c['cue_to_finish'] for c in cuts if c['role']=='measured']),release_lag=quant([r['scheduler_release_lag_seconds'] for r in requests.values()]),waiting_frames=len(frames),eligible_frames=sum(bool(f['eligible']) for f in frames),request_token_offset_verified_at_all_cuts=True)
 dump(out/'extraction-summary.json',info);return info
if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,default=Path(__file__).resolve().parent/'derived');a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
 for label,root in SOURCES:
  x=extract(label,root,a.out/label);print(json.dumps(x),flush=True)
