"""Paired token/budget paths; prefix divergence is evidence of non-identical trajectories, not a cause label."""
import argparse,json
from pathlib import Path
from extract import SOURCES,dump
p=argparse.ArgumentParser();p.add_argument('--derived',type=Path,default=Path(__file__).resolve().parent/'derived');a=p.parse_args();D=a.derived;roots=dict(SOURCES);result=[]
for run in ['b0','b1']:
 rows=json.loads((D/run/'requests.json').read_text());idx={(r['phase'],r['id']):r for r in rows};root=roots[run]
 for l in rows:
  if l['role']!='measured' or l['policy']!='live':continue
  aa=idx[(l['phase'].replace('-live','-arrival'),l['id'])];x=json.loads((root/'requests'/(l['key']+'.json')).read_text());y=json.loads((root/'requests'/(aa['key']+'.json')).read_text());prefix=0
  for u,v in zip(x['token_ids'],y['token_ids']):
   if u!=v:break
   prefix+=1
  path='direct_cut' if l['cut_time'] is not None else 'different_admission_budget' if l['initial_budget']!=aa['initial_budget'] else 'same_budget_uncut'
  result.append(dict(run=run,condition=l['phase'].split('-')[0],id=l['id'],cut=l['cut_tokens'],live_initial=l['initial_budget'],arrival_initial=aa['initial_budget'],budget_path=path,shared_token_prefix=prefix,identical_tokens=x['token_ids']==y['token_ids'],prefix_diverges_before_cut=bool(l['cut_tokens'] is not None and prefix<l['cut_tokens']),correctness_changed=l['correct']!=aa['correct'],good_changed=l['good']!=aa['good']))
assert len(result)==40
dump(D/'paired-token-paths.json',result)
print(json.dumps(dict(pairs=len(result),identical=sum(r['identical_tokens'] for r in result),cut_targets=sum(r['cut'] is not None for r in result),prefix_diverges_before_cut=sum(r['prefix_diverges_before_cut'] for r in result),admission_changes=sum(r['live_initial']!=r['arrival_initial'] for r in result)),indent=2))
