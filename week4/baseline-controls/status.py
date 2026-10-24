"""Read staged Slurm/accounting and safe phase progress using local cluster settings."""
import json
from datetime import datetime
from zoneinfo import ZoneInfo
import os
from pathlib import Path
import shlex
import subprocess

HERE=Path(__file__).resolve().parent
ledger=json.loads((HERE/'campaign.json').read_text())
ids=[j['job'] for j in ledger['jobs']]
if ledger.get('postprocessing'):ids.append(ledger['postprocessing']['job'])
assert all(job.isdigit() for job in ids)
script=r'''
import json,subprocess
from pathlib import Path
ids=IDS
result=subprocess.run(['sacct','-X','-j',','.join(ids),'--noheader','--parsable2','--format=JobIDRaw,State,ElapsedRaw,ExitCode'],capture_output=True,text=True)
accounting={}
for line in result.stdout.splitlines():
 f=line.split('|')
 if f[0] in ids:accounting[f[0]]=dict(state=f[1].split()[0],elapsed_seconds=int(f[2] or 0),exit_code=f[3])
queue=subprocess.run(['squeue','-j',','.join(ids),'-h','-o','%i|%T|%r'],capture_output=True,text=True)
for line in queue.stdout.splitlines():
 f=line.split('|')
 if f[0] in ids:accounting.setdefault(f[0],{}).update(state=f[1],reason=f[2])
output=[]
for job in ids:
 root=Path('week4/baseline-controls/results')/('job-'+job)
 row=dict(job=job,**accounting.get(job,dict(state='UNKNOWN')))
 progress=root/'progress.json'
 if progress.exists():row['phases']=[dict(phase=p['phase'],completed=p['completed'],terminal_receipts=sum(r['status']=='terminal' for r in p['client'])) for p in json.loads(progress.read_text())]
 for name in ['runtime-fit.json','mechanical-validation.json']:
  p=root/name
  if p.exists():
   d=json.loads(p.read_text());row[name]={k:v for k,v in d.items() if k not in ['rows','overlap_by_phase']}
 failed=root/'run-failed.json'
 if failed.exists():row['failure_type']=json.loads(failed.read_text())['error']
 output.append(row)
print(json.dumps(output,indent=2))
'''.replace('IDS',repr(ids))
command='cd '+shlex.quote(os.environ['PACE_PROJECT_ROOT'])+' && python3 -c '+shlex.quote(script)
result=subprocess.check_output(['ssh','-o','BatchMode=yes','-o','ConnectTimeout=20',os.environ['PACE_SSH_TARGET'],command],text=True)
data=dict(captured_at=datetime.now(ZoneInfo('America/New_York')).isoformat(),jobs=json.loads(result))
(HERE/'status.json').write_text(json.dumps(data,indent=2)+'\n');print(json.dumps(data,indent=2))
