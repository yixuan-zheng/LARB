"""Optional local startup observer; never submits or retries jobs."""
import json,subprocess,sys,time
from pathlib import Path
h=Path(__file__).resolve().parent
for _ in range(180):
    result=subprocess.run([sys.executable,'-B',str(h/'status.py')],stdout=subprocess.DEVNULL)
    if result.returncode:print('READ_ERROR: cluster chain remains independent',flush=True);time.sleep(60);continue
    status=json.loads((h/'status.json').read_text());jobs={j['job']:j for j in status['jobs']}
    progress=[(j['job'],j['state'],[(p['phase'],p['terminal_receipts']) for p in j.get('phases',[])]) for j in status['jobs']]
    print('PROGRESS',status['captured_at'],progress,flush=True)
    if any(j['state'] in ['FAILED','TIMEOUT','OUT_OF_MEMORY','NODE_FAIL','CANCELLED'] for j in status['jobs']):
        print('STOP_FOR_DIAGNOSIS',flush=True);break
    gate=jobs['6512258'];burst=jobs['6512259']
    if gate['state']=='COMPLETED' and gate.get('mechanical-validation.json',{}).get('passed'):
        if any(p['phase']!='calib' and p['terminal_receipts']>=3 for p in burst.get('phases',[])):
            print('READY_FOR_UNATTENDED: gate audited and graded; first matched comparison generating real measured responses.',flush=True);break
    time.sleep(60)
