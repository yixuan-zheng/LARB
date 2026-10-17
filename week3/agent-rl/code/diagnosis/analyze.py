import json,pathlib,collections,re,statistics,csv
ROOT=pathlib.Path('outputs/agent-rl-tools/raw');OUT=pathlib.Path('outputs/agent-rl-diagnosis')
def quant(a):
 a=sorted(a)
 def q(p):
  z=(len(a)-1)*p;i=int(z);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(z-i)
 return {'min':a[0],'median':q(.5),'p90':q(.9),'max':a[-1]} if a else None
def parse(t):
 blocks=[];cur=None;step=None
 for l in re.sub(r'\x1b\[[0-9;]*m','',t).splitlines():
  m=re.search(r'Train step (\d+)/',l)
  if m:step=int(m[1])
  if 'StatsLogger INFO: Stats (' in l:cur={'step':step,'metrics':{}};blocks.append(cur)
  if cur is not None and '│' in l:
   c=[x.strip() for x in l.split('│')[1:-1]]
   for i in range(0,len(c)-1,2):
    try:cur['metrics'][c[i]]=float(c[i+1])
    except ValueError:pass
 return [b for b in blocks if 'ppo_actor/update/grad_norm' in b['metrics'] and b['step']]
summary={};batchrows=[];grouprows=[]
for trial in ['calcasync','calccapped','calcfresh','calcdynamic']:
 rows=[json.loads(l) for p in (ROOT/trial/'profiles').glob('*.jsonl') for l in p.read_text().splitlines() if l.strip()]
 allstats=parse((ROOT/trial/'native-run.log').read_text());stats=allstats[:8];n=len(stats)
 cons=sorted([r for r in rows if r['event']=='batch_consumed' and r['version']<n],key=lambda r:r['time'])
 starts=collections.defaultdict(list);ends=collections.defaultdict(list)
 for r in rows:
  if r.get('is_eval',True):continue
  if r['event']=='workflow_start':starts[r['task_id']].append(r)
  if r['event']=='workflow_end':ends[r['task_id']].append(r)
 groups={}
 for k,v in starts.items():
  ee=ends[k];complete=len(ee)==4 and len({r['sample_idx'] for r in ee})==4
  groups[k]={'start':min(r['time'] for r in v),'ready':max(r['time'] for r in ee) if complete else None,'mixed':len({r['reward'] for r in ee})>1 if complete else None,'ends':ee}
 used={};resident=[];critical=[]
 for c in cons:
  s=c['time']-c['seconds'];t=c['time'];ids=c['task_ids'];assert len(ids)==8
  assert all(groups[k]['ready'] is not None for k in ids)
  previous=set(used)
  ready=[k for k,g in groups.items() if g['ready'] is not None and g['ready']<=s and k not in previous and (trial!='calcdynamic' or g['mixed'])]
  unfinished=[k for k,g in groups.items() if g['start']<=s and (g['ready'] is None or g['ready']>s)]
  last=max(groups[k]['ready'] for k in ids);gap=t-last
  critical.append(gap)
  batchrows.append({'trial':trial,'version':c['version'],'collection_seconds':c['seconds'],'start':s,'end':t,'observed_ready_unconsumed_at_start':len(ready),'observed_unfinished_at_start':len(unfinished),'returned_groups_ready_at_start':sum(groups[k]['ready']<=s for k in ids),'last_member_end_to_return_seconds':gap})
  for k in ids:
   g=groups[k];age=[c['version']-r['retained_version_min'] for r in g['ends'] if r.get('retained_version_min') is not None]
   lag=t-g['ready'];resident.append(lag);used[k]=c
   grouprows.append({'trial':trial,'task_id':k,'consume_version':c['version'],'mixed':g['mixed'],'start':g['start'],'ready':g['ready'],'consume':t,'observed_group_duration':g['ready']-g['start'],'ready_to_consume_seconds':lag,'max_retained_token_age':max(age) if age else None})
 stage={k:sum(b['metrics'].get(k,0) for b in stats) for k in {k for b in stats for k in b['metrics']} if k.startswith('timeperf/') and k!='timeperf/eval'}
 denom=sum(stage.values());collection=sum(c['seconds'] for c in cons)
 begin=cons[0]['time']-cons[0]['seconds'];finish=cons[-1]['time'];window=finish-begin
 generated=sum(r['output_tokens'] for r in rows if r['event']=='generation_end' and not r['is_eval'] and begin<=r['time']<=finish)
 mix=sum(groups[k]['mixed'] for k in used)
 summary[trial]={'updates':n,'groups':len(used),'mixed_consumed_groups':mix,'dispatcher_collection_seconds':collection,'native_stage_seconds_excluding_eval':stage,'native_stage_sum_excluding_eval':denom,'native_rollout_fraction_of_stage_sum':stage.get('timeperf/rollout',0)/denom,'collection_seconds_per_update':quant([c['seconds'] for c in cons]),'last_member_end_to_return_seconds':quant(critical),'group_ready_to_return_seconds':quant(resident),'first_collection_to_last_return_seconds':window,'mixed_groups_per_observed_window_second':mix/window,'completed_generation_tokens_in_window':generated,'completed_generation_tokens_per_window_second':generated/window,'initial_collection_seconds':cons[0]['seconds'],'later_collection_seconds':sum(c['seconds'] for c in cons[1:])}
for name,data in [('batch-timeline',batchrows),('group-timeline',grouprows)]:
 with (OUT/(name+'.csv')).open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
(OUT/'diagnosis.json').write_text(json.dumps(summary,indent=2))
print(json.dumps(summary,indent=2))

# Separate the longer wide run into eight-update windows, without comparing policies as identical work.
rows=[json.loads(l) for p in (ROOT/'calcasync/profiles').glob('*.jsonl') for l in p.read_text().splitlines()]
stats=parse((ROOT/'calcasync/native-run.log').read_text())
windows=[]
for lo,hi in [(0,8),(8,16),(16,24)]:
 a=stats[lo:hi]; c=[r for r in rows if r['event']=='batch_consumed' and lo<=r['version']<hi]
 stages={k:sum(b['metrics'].get(k,0) for b in a) for k in {k for b in a for k in b['metrics']} if k.startswith('timeperf/') and k!='timeperf/eval'}
 windows.append({'versions':[lo,hi],'collection_seconds':sum(r['seconds'] for r in c),'collection_per_update':sum(r['seconds'] for r in c)/len(c),'native_stage_sum_excluding_eval':sum(stages.values()),'rollout_fraction':stages['timeperf/rollout']/sum(stages.values())})
(OUT/'wide-training-windows.json').write_text(json.dumps(windows,indent=2))
print('WINDOWS',json.dumps(windows))
