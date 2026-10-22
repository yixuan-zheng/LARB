"""Observe the pre-submitted chain, collect completed evidence, and grade without new GPU submissions."""
import argparse
from datetime import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import time
from zoneinfo import ZoneInfo

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--interval',type=int,default=60);ap.add_argument('--max-wall-hours',type=float,default=24);args=ap.parse_args()
assert args.interval>=30 and 0<args.max_wall_hours<=48
key=hashlib.sha256(str(HERE).encode()).hexdigest()[:12]
lock=(Path(tempfile.gettempdir())/f'larb5b-watch-{key}.lock').open('w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
start=time.monotonic();failed_reads=0;done=set()

def write(name,data):
    p=HERE/name;tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(p)

def report(ledger):
    rows=[]
    for job in ledger['jobs']:
        p=HERE/'results'/('job-'+job['job'])/'analysis/summary.json'
        if not p.exists():continue
        result=json.loads(p.read_text());policies={r['policy']:r for r in result['summary']}
        rows.append((job,policies))
    text=['# Reserved validation results','',f'{len(rows)}/6 stages collected and graded. The complete-campaign decision is made only after all six matched stages. Correctness does not gate continuation.','',
          '| Stage | Condition / shard | Admission on time | Live on time | Admission eventual | Live eventual | GPU time |',
          '| --- | --- | --- | --- | --- | --- | --- |']
    for job,p in rows:
        seconds=job.get('elapsed_seconds',0)
        text.append(f"| {job['stage']} | {job['condition']} / {job['shard']} | {p['admission']['correct_on_time']}/24 | {p['live']['correct_on_time']}/24 | {p['admission']['completed_correct']}/24 | {p['live']['completed_correct']}/24 | {seconds//60}:{seconds%60:02d} |")
    text+=['','Each stage has 12 unique questions replayed twice; all stages together cover only 24 unique questions. Caps, late completions, and wrong answers stay in the denominator. Each run directory includes raw responses, source/input/trace hashes, a mechanical audit, grades, review queue, and accounting.','',
           'No controller changes, quality-driven retries, or question substitutions were made. Intermediate rows are partial results and do not select later stages. The frozen [plan](../evaluation-plan/EVALUATION.md) explains the endpoints and uncertainty.']
    if len(rows)==6:
        summary=json.loads((HERE/'analysis/summary.json').read_text())
        text+=['','## Complete campaign','',f"Primary pooled pressure success-fraction difference (live minus admission): **{100*summary['primary_pressure_success_fraction_difference']:+.2f} percentage points**.",
               f"Eventual correctness difference across all conditions: **{100*summary['eventual_correctness_difference']:+.2f} percentage points**.",
               f"Observed continuation screen passed: **{summary['screen_passed']}**. This is a diagnostic decision rule, not an accuracy-risk or generalization guarantee.",'',
               '| Condition | Policy | Correct on time /48 | Eventual correct /48 | Median client seconds | Binding live cutoffs |',
               '| --- | --- | --- | --- | --- | --- |']
        for r in summary['per_condition']:
            text.append(f"| {r['condition']} | {r['policy']} | {r['correct_on_time']} | {r['completed_correct']} | {r['median_client_seconds']:.2f} | {r['binding_live_cutoffs']} |")
        seconds=sum(j.get('elapsed_seconds',0) for j in ledger['jobs'])
        text+=['',f"GPU allocations used **{seconds/3600:.3f} GPU-hours** including startup, calibration, inference, and drain. No GPU repair allocation was used.",'',
               'See [aggregate data](analysis/summary.json) for condition/block differences, question-cluster sensitivity, and per-run sources. The bootstrap is descriptive conditional sensitivity; queue coupling and two question shards limit independent inference. Rates use each job’s saved fixed horizon rather than pooling unlike calibrated horizons.']
    (HERE/'REPORT.md').write_text('\n'.join(text)+'\n')

while time.monotonic()-start<args.max_wall_hours*3600:
    try:
        subprocess.run([sys.executable,'-B',str(HERE/'status.py')],check=True,stdout=subprocess.DEVNULL)
        status=json.loads((HERE/'status.json').read_text());failed_reads=0
    except subprocess.CalledProcessError:
        failed_reads+=1
        if failed_reads>=3:
            write('watch-state.json',dict(status='status_reads_unavailable',gpu_chain_unaffected=True));break
        time.sleep(args.interval);continue
    ledger=json.loads((HERE/'campaign.json').read_text());states={r['job']:r for r in status['jobs']}
    for job in ledger['jobs']:
        state=states.get(job['job'],{})
        if state.get('state')=='COMPLETED':
            job.update(status='complete',elapsed_seconds=state['elapsed_seconds'],exit_code=state['exit_code'])
            root=HERE/'results'/('job-'+job['job'])
            if not (root/'analysis/summary.json').exists():
                subprocess.run([sys.executable,'-B',str(HERE/'collect.py'),'--job',job['job'],'--exclude-analysis'],check=True)
                subprocess.run([sys.executable,'-B',str(HERE/'analyze.py'),'--root',str(root)],check=True,stdout=subprocess.DEVNULL)
            result=json.loads((root/'analysis/summary.json').read_text());assert result['complete'] and result['validation_passed']
            job['mechanical_validation_passed']=True
            if job['job'] not in done:
                print('COLLECTED',job['job'],job['condition'],job['shard'],{r['policy']:(r['correct_on_time'],r['completed_correct']) for r in result['summary']},flush=True)
                done.add(job['job'])
        elif state.get('state') in ['FAILED','CANCELLED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED','BOOT_FAIL','DEADLINE','REVOKED']:
            job.update(status='stopped_for_diagnosis',scheduler_state=state['state'])
            ledger['status']='stopped_for_diagnosis';write('campaign.json',ledger)
            write('watch-state.json',dict(status='stopped_for_diagnosis',job=job['job'],automatic_gpu_retries=0))
            print('STOPPED',job['job'],state['state'],'No automatic GPU retry.',flush=True);sys.exit(2)
        else:job['status']=state.get('state','unknown').lower()
    complete=all(j['status']=='complete' for j in ledger['jobs'])
    ledger['allocated_gpu_seconds_completed']=sum(j.get('elapsed_seconds',0) for j in ledger['jobs'] if j['status']=='complete')
    if complete:
        roots=[str(HERE/'results'/('job-'+j['job'])) for j in ledger['jobs']]
        subprocess.run([sys.executable,'-B',str(HERE/'analyze.py'),'--aggregate',*roots,'--out',str(HERE/'analysis')],check=True,stdout=subprocess.DEVNULL)
        ledger['status']='complete_and_locally_graded';write('campaign.json',ledger);report(ledger)
        write('watch-state.json',dict(status='complete_and_locally_graded',completed_jobs=6,automatic_gpu_retries=0))
        print('COMPLETE: six stages collected; all 288 outcomes graded and aggregated.',flush=True);break
    running=[r for r in status['jobs'] if r.get('state')=='RUNNING']
    ledger['status']='running';write('campaign.json',ledger);report(ledger)
    write('watch-state.json',dict(status='running',captured_at=status['captured_at'],completed_jobs=sum(j['status']=='complete' for j in ledger['jobs']),automatic_gpu_retries=0))
    print('PROGRESS',status['captured_at'],[(r['job'],[(p['phase'],p['terminal_receipts']) for p in r.get('phases',[])]) for r in running],flush=True)
    time.sleep(args.interval)
else:write('watch-state.json',dict(status='watch_wall_limit',gpu_chain_unaffected=True))
