"""Reproduce compact published accounting from derived evidence; never inference or raw grading."""
import csv,hashlib,json,math,statistics
from collections import Counter,defaultdict
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];E=ROOT/'evidence'
def read(name):return json.loads((E/name).read_text())
def close(a,b):assert math.isclose(a,b,rel_tol=1e-10,abs_tol=1e-8),(a,b)
def q90(v):return sorted(v)[max(0,int(.9*len(v)+.999)-1)]
def distribution(v):return dict(n=len(v),mean=statistics.mean(v),median=statistics.median(v),p90=q90(v),max=max(v))
def main():
 expected=read('audit-summary.json');rows=read('response-metrics.json');assert len({(r['run'],r['key']) for r in rows})==len(rows)==244
 assert sum(r['role']=='measured' for r in rows)==232 and sum(r['role']=='probe' for r in rows)==12
 assert all(r['present'] and r['complete'] and r['good']==bool(r['correct'] and r['timely']) for r in rows)
 assert all(r['normal'] or not r['correct'] for r in rows)
 phase_summary=read('phase-summary.json')
 for run,phases in phase_summary.items():
  for p in phases:
   rr=[r for r in rows if r['run']==run and r['phase']==p['phase']]
   assert len(rr)==p['n'] and sum(r['correct'] for r in rr)==p['correct'] and sum(r['good'] for r in rr)==p['good']
   assert sum(r['output_tokens'] for r in rr)==p['output_tokens'] and sum(not r['normal'] for r in rr)==p['caps']
 pool=[]
 for saved in expected['pooled']:
  rr=[r for r in rows if r['run'] in ['b0','b1'] and r['role']=='measured' and r['policy']==saved['policy']]
  r=dict(policy=saved['policy'],n=len(rr),correct=sum(x['correct'] for x in rr),good=sum(x['good'] for x in rr),caps=sum(not x['normal'] for x in rr),output_tokens=sum(x['output_tokens'] for x in rr),mean_queue=statistics.mean(x['queue_seconds'] for x in rr),mean_service=statistics.mean(x['service_seconds'] for x in rr),mean_latency=statistics.mean(x['latency_seconds'] for x in rr))
  for k,v in r.items():
   if isinstance(v,float):close(v,saved[k])
   else:assert v==saved[k],k
  pool.append(r)
 idx={(r['run'],r['phase'],r['id']):r for r in rows};categories=[];gains=losses=0;net_correct=0
 for l in rows:
  if l['run'] not in ['b0','b1'] or l['role']!='measured' or l['policy']!='live':continue
  a=idx[(l['run'],l['phase'].replace('-live','-arrival'),l['id'])]
  if l['correct'] and a['correct']:category='both_correct_live_timely_only' if l['good'] and not a['good'] else 'both_correct_arrival_timely_only' if a['good'] and not l['good'] else 'both_correct_both_timely' if l['good'] else 'both_correct_both_late'
  elif l['correct']:category='live_correct_only'
  elif a['correct']:category='arrival_correct_only'
  else:category='both_incorrect'
  categories.append(category);gains+=l['good'] and not a['good'];losses+=a['good'] and not l['good'];net_correct+=int(l['correct'])-int(a['correct'])
 assert dict(Counter(categories))==expected['paired_categories'] and gains==losses==3 and net_correct==-3
 with (E/'paired-outcomes.csv').open() as f:csvrows=list(csv.DictReader(f))
 assert len(csvrows)==40 and sum(int(r['net_good']) for r in csvrows)==0 and sum(int(r['net_correct']) for r in csvrows)==-3
 cuts=[c for c in read('cut-timelines.json') if c['role']=='measured'];assert len(cuts)==expected['cuts']['n']==24
 for field,source in [('cut_to_finish','cut_to_finish'),('cue_to_finish','cue_to_finish'),('cut_to_cue','cut_to_cue'),('remaining_8k_headroom','remaining_8k_tokens')]:
  v=[c[source] for c in cuts];got=dict(distribution(v),min=min(v))
  for k,x in got.items():close(x,expected['cuts'][field][k])
 releases=read('release-events.json');assert len(releases)==105 and len({(r['run'],r['step']) for r in releases})==104 and all(r['new_prior_waiters_same_step'] for r in releases)
 paths=read('budget-paths.json');assert len(paths)==40 and sum(r['cut'] is not None for r in paths)==16 and sum(r['prefix_diverges_before_cut'] for r in paths)==10 and sum(r['identical_tokens'] for r in paths)==8
 validation=read('prediction-validation.json');ps=read('prediction-summary.json')
 for info in ps:
  vv=[r for r in validation if r['run']==info['run']];assert len(vv)==info['validation_waiter_requests']
  for metric,key in [('median_abs_error','median_abs_error_per_request'),('median_signed_error','median_signed_error_per_request')]:
   for k,v in distribution([r[metric] for r in vv]).items():close(v,info[key][k])
  assert info['robust_rescue_states']==0
 assert len(read('decision-opportunities.json'))==15
 provenance=read('source-provenance.json');assert sum(len(r['input_sha256']) for r in provenance)==21
 manifest=ROOT/'MANIFEST.json'
 if manifest.exists():
  for name,digest in json.loads(manifest.read_text()).items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest,name
 print(json.dumps(dict(compact_accounting='PASS',derived_records=len(rows),measured_records=232,paired_cases=40,queued_release_steps=104,goodput_gains=gains,goodput_losses=losses,net_correct=net_correct,pooled=pool,limits='Derived accounting only: full token/extraction/event/predictor audits require the preserved private input collections.'),indent=2))
if __name__=='__main__':main()
