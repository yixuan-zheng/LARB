"""CPU reproduction from compact per-response metrics and checkpoint features."""
import csv,json,statistics,sys
from pathlib import Path
from rules_2k import extend as extend2
from rules_4k import extend as extend4
HERE=Path(__file__).resolve().parent;ROOT=HERE.parent;E=ROOT/'evidence'
def read(p):return json.loads(p.read_text())
def metric(rr):return dict(correct=sum(x['correct'] for x in rr),accuracy=statistics.mean(x['correct'] for x in rr),mean_tokens=statistics.mean(x['output_tokens'] for x in rr),mean_seconds=statistics.mean(x['elapsed_seconds'] for x in rr))
def main():
 rows=[]
 for r in csv.DictReader((E/'response-metrics.csv').open()):
  for k in ['id','seed','budget','output_tokens']:r[k]=int(r[k])
  r['correct']=r['correct']=='True';r['elapsed_seconds']=float(r['elapsed_seconds']);rows.append(r)
 assert len(rows)==240 and len({x['key'] for x in rows})==240 and len({x['id'] for x in rows})==30
 cells={}
 for r in rows:cells.setdefault((r['id'],r['seed']),{})[r['budget']]=r
 keys=sorted(cells);qs=sorted({k[0] for k in keys});result={}
 saved=read(E/'budget-summary.json')['pooled']['summary']
 for budget in [2048,4096,8192,16384]:
  mm=metric([cells[k][budget] for k in keys]);orig=next(x for x in saved if x['budget']==budget);assert mm['correct']==orig['correct'] and abs(mm['mean_seconds']-orig['mean_seconds'])<1e-8;result[str(budget)]=mm
 for name,short,fn in [('phase-a',2048,extend2),('phase-a2',4096,extend4)]:
  if short==2048:
   features={(x['id'],x['seed']):x for x in read(E/'phase-a-features.json')};eligible=set(keys);spec=read(E/'phase-a-protocol.json');rules=spec['rules'];expected=read(E/'phase-a-results.json')['leave_one_question_out']
  else:
   rr=read(E/'phase-a2-decisions.json');features={(x['id'],x['seed']):x['features'] for x in rr};eligible={(x['id'],x['seed']) for x in rr if x['eligible']};spec=read(E/'phase-a2-signals-protocol.json');rules=spec['rules']+['fixed4k'];expected=read(E/'phase-a2-signals-results.json')['out_of_fold']
  def route(rule,k):return 8192 if k in eligible and fn(rule,features[k]) else short
  chosen=[]
  for q in qs:
   train=[k for k in keys if k[0]!=q];test=[k for k in keys if k[0]==q];base=metric([cells[k][8192] for k in train]);scores={r:metric([cells[k][route(r,k)] for k in train]) for r in rules};feasible=[r for r,s in scores.items() if s['mean_tokens']<=.75*base['mean_tokens'] and s['mean_seconds']<=.75*base['mean_seconds']]
   rule=min(feasible,key=lambda r:(-scores[r]['accuracy'],scores[r]['mean_tokens'],r)) if feasible else (min(rules,key=lambda r:(scores[r]['mean_tokens'],r)) if short==2048 else 'fixed4k')
   chosen.extend(cells[k][route(rule,k)] for k in test)
  mm=metric(chosen);assert mm['correct']==expected['correct'] and abs(mm['mean_tokens']-expected['mean_tokens'])<1e-8 and abs(mm['mean_seconds']-expected['mean_seconds'])<1e-8;result[name+'-oof']=mm
 print(json.dumps(dict(verified=True,results=result,limits='Reproduces aggregate metrics and grouped rule selection from derived features. Raw generation/tokenization/grading audits are not independently reproducible from this compact package.'),indent=2))
if __name__=='__main__':main()
