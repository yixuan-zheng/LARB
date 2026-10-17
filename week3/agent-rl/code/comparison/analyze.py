"""Analyze the fully drained fixed-policy comparison using worker filter events."""
import json,pathlib,collections,csv,statistics,hashlib
root=pathlib.Path('outputs/agent-rl-comparison');raw=root/'raw'
rows=[json.loads(l) for p in (raw/'profiles/tirgatecompare').glob('events-*.jsonl') for l in p.read_text().splitlines() if l.strip()]
rows.sort(key=lambda x:x['time'])
def q(a):
 a=sorted(a)
 if not a:return None
 def f(p):
  z=(len(a)-1)*p;i=int(z);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(z-i)
 return dict(min=a[0],median=f(.5),p90=f(.9),max=a[-1])
starts={r['phase']:r for r in rows if r['event']=='phase_start'};ends={r['phase']:r for r in rows if r['event']=='phase_end'}
result={};curves=[];cohorts={};checks={}
for phase,start in starts.items():
 if phase not in ends:continue
 end=ends[phase];eps=[r for r in rows if r['event']=='gate_episode_end' and r['phase']==phase]
 admissions=[r for r in rows if r['event']=='gate_admission' and r['phase']==phase]
 filters=[r for r in rows if r['event']=='group_filter' and r['phase']==phase]
 groups=collections.defaultdict(list)
 for r in eps:groups[r['source_id']].append(r)
 mixed=sum(len({r['reward'] for r in g})>1 for g in groups.values())
 checks[phase]=dict(complete_episodes=len(eps)==start['groups']*4,complete_groups=len(groups)==start['groups'] and all(len(g)==4 and len({r['sample_idx'] for r in g})==4 for g in groups.values()),filter_rows_four=all(r['rows']==4 for r in filters),filter_accounting=not start['filtered'] or len(filters)==start['groups'] and sum(r['accepted'] for r in filters)==mixed==end['returned_groups'])
 assert all(checks[phase].values()),(phase,checks[phase])
 # Native profile generation events do not contain phase; bracket by sequential, drained phase windows.
 gen=[r for r in rows if r['event']=='generation_end' and start['time']<=r['time']<=end['time']]
 toks=sum(r['output_tokens'] for r in gen);accepted=sorted([r for r in filters if r['accepted']],key=lambda x:x['time'])
 ts=[r['time']-start['time'] for r in accepted]
 for i,t in enumerate(ts):curves.append(dict(phase=phase,accepted_groups=i+1,seconds=t))
 laststats=[r['gate_stats'] for r in eps if r['gate_stats']]
 stats={k:max(r[k] for r in laststats) for k in laststats[0]} if laststats else None
 waits=[r['wait_seconds'] for r in admissions]
 result[phase]=dict(policy=start['policy'],capacity=start['capacity'],wall_seconds=end['seconds'],episodes=len(eps),mixed_groups=mixed,accepted_groups=end['returned_groups'],reward_mean=statistics.mean(r['reward'] for r in eps),generated_tokens=toks,tokens_per_second=toks/end['seconds'],mixed_groups_per_second=mixed/end['seconds'],generation_calls=len(gen),gate_admissions=len(admissions),gate_wait_seconds=q(waits),queued_admissions=sum(v>.001 for v in waits),max_recorded_queue_depth=max((r['queue_depth'] for r in admissions),default=0),stats=stats,accepted_times=ts)
 cohorts[phase]={(r['source_id'],r['sample_idx']):r['reward'] for r in eps}
phases=[p for p in result if p!='preflight']
if phases:
 k=min(result[p]['mixed_groups'] for p in phases)
 for p in phases:result[p]['time_to_common_k_mixed_groups']=result[p]['accepted_times'][k-1] if k else None
 checks['common_k']=k
 baseline=cohorts[phases[0]]
 checks['outcome_differences_vs_first_arm']={p:sum(v!=baseline.get(key) for key,v in cohorts[p].items()) for p in phases}
 mixed_sources={p:{sid for sid in {key[0] for key in cohorts[p]} if len({v for (source,member),v in cohorts[p].items() if source==sid})>1} for p in phases}
 common=set.intersection(*(mixed_sources[p] for p in phases))
 checks['common_mixed_sources']=sorted(common)
 for p in phases:
  ff=[r for r in rows if r['event']=='group_filter' and r['phase']==p and r['accepted'] and r['source_id'] in common]
  result[p]['time_to_all_common_mixed_sources']=max((r['time']-starts[p]['time'] for r in ff),default=None)

(root/'results.json').write_text(json.dumps(result,indent=2));(root/'checks.json').write_text(json.dumps(checks,indent=2))
with (root/'delivery-curves.csv').open('w') as f:
 w=csv.DictWriter(f,fieldnames=['phase','accepted_groups','seconds']);w.writeheader();w.writerows(curves)
print(json.dumps(result,indent=2));print(json.dumps(checks,indent=2))
