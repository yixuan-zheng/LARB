#!/bin/bash
#SBATCH --job-name=larb-w4-score
#SBATCH --account=coc
#SBATCH --partition=coc-cpu
#SBATCH --qos=coc-ice
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
source vllm-proof-env/bin/activate
export PYTHONPATH="$PWD/week4/reserved-validation/.analysis-deps"
python -B - <<'PY'
from pathlib import Path
import json
import subprocess
import sys
root=Path.cwd()
metrics=root/'week4/step1/controlled-comparison/metrics.py'
assert metrics.is_file(), 'Deploy the tracked controlled-comparison/metrics.py before CPU grading'
ledger=json.loads((root/'week4/reserved-validation/campaign.json').read_text())
assert len(ledger['jobs'])==6
runs=[root/'week4/reserved-validation/results'/('job-'+job['job']) for job in ledger['jobs']]
for job,run in zip(ledger['jobs'],runs):
    accounting=subprocess.check_output(['sacct','-X','-j',job['job'],'--noheader','--parsable2','--format=JobIDRaw,State,ElapsedRaw,ExitCode,AllocTRES,Start,End'],text=True)
    (run/'accounting.txt').write_text(accounting)
    fields=next(line.split('|') for line in accounting.splitlines() if line.split('|')[0]==job['job'])
    assert fields[1]=='COMPLETED' and fields[3]=='0:0'
    job.update(status='complete',elapsed_seconds=int(fields[2]),exit_code=fields[3])
    subprocess.run([sys.executable,'-B','week4/reserved-validation/analyze.py','--root',str(run)],check=True)
subprocess.run([sys.executable,'-B','week4/reserved-validation/analyze.py','--aggregate',*[str(r) for r in runs],
                '--out',str(root/'week4/reserved-validation/analysis')],check=True)
ledger['status']='complete_and_graded'
ledger['allocated_gpu_seconds']=sum(job['elapsed_seconds'] for job in ledger['jobs'])
assert ledger['allocated_gpu_seconds']<=24*3600
(root/'week4/reserved-validation/campaign.json').write_text(json.dumps(ledger,indent=2)+'\n')
print('Complete campaign graded on CPU; GPU allocations ended before scoring.')
PY
