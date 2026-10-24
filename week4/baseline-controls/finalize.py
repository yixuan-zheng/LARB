"""Cluster-side CPU finalizer, also produces an honest report after failures."""
import json,os,subprocess,sys,traceback
from pathlib import Path
HERE=Path(__file__).resolve().parent
ledger=json.loads((HERE/'campaign.json').read_text());results=[];errors=[]
for job in ledger['jobs']:
 root=HERE/'results'/('job-'+job['job'])
 try:
  account=subprocess.check_output(['sacct','-X','-j',job['job'],'-n','-P','--format=JobIDRaw,State,ElapsedRaw,ExitCode,AllocTRES,Start,End'],text=True)
  root.mkdir(parents=True,exist_ok=True);(root/'accounting.txt').write_text(account)
  state=next(row.split('|') for row in account.splitlines() if row.split('|')[0]==job['job'])
  job.update(state=state[1],elapsed_seconds=int(state[2]),exit_code=state[3])
  if state[1]!='COMPLETED':raise RuntimeError('Stage did not complete: '+state[1])
  subprocess.run([sys.executable,'-B',str(HERE/'analyze.py'),'--root',str(root)],check=True)
  results.append(dict(stage=job['stage'],job=job['job'],condition=job['condition'],summary=json.loads((root/'analysis/summary.json').read_text())))
 except Exception as e:errors.append(dict(job=job['job'],error=type(e).__name__,message=str(e).replace(str(HERE),'<EXECUTION_FOLDER>')))
measured=[r for r in results if r['condition']!='gate'];complete=len(measured)==2 and not errors
out=HERE/'analysis';out.mkdir(exist_ok=True)
report=dict(complete=complete,results=results,errors=errors,measured_outcomes=sum(r['summary']['measured_outcomes'] for r in measured),unique_questions=12 if measured else 0,allocated_gpu_seconds=sum(j.get('elapsed_seconds',0) for j in ledger['jobs']),note='Development comparison; repeated questions, no population accuracy guarantee; all fixed alternatives reported, no outcome-selected reruns.')
(out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
text=['# Fixed-budget concurrent controls','',f'Complete campaign: {complete}. Measured outcomes: {report["measured_outcomes"]}/192.','', '| Condition | Policy | On time /24 | Eventual /24 | Median seconds |','| --- | --- | --- | --- | --- |']
for r in measured:
 for s in r['summary']['summary']:text.append(f"| {r['condition']} | {s['policy']} | {s['correct_on_time']} | {s['completed_correct']} | {s['median_client_seconds']:.2f} |")
text+=['',f"GPU allocation time: {report['allocated_gpu_seconds']/3600:.3f} hours.",'','Errors: '+json.dumps(errors),'','Only 12 unique exposed questions, repeated by condition/block. See PLAN.md for scope and cost limits.']
(HERE/'REPORT.md').write_text('\n'.join(text)+'\n');ledger['status']='complete_and_graded' if complete else 'partial_or_failed';ledger['errors']=errors
(HERE/'campaign.json').write_text(json.dumps(ledger,indent=2)+'\n')
if not complete:raise SystemExit(2)
