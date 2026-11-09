"""Explicit calibration OR approved frozen-trace pilot. Never submits Slurm jobs."""
import argparse,asyncio,hashlib,json,os,subprocess,sys,time
from pathlib import Path
from workload import ranked_ids,validate_trace
from gate import probe_plan,verify
HERE=Path(__file__).resolve().parent

def atomic(path,v):
 tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(v,indent=2)+'\n');tmp.replace(path)

async def run(args,server):
 import aiohttp
 root=args.out;spec=json.loads((HERE/'spec.json').read_text());base='http://127.0.0.1:'+os.environ['BUDGET_PORT'];progress=[]
 async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=spec['phase_drain_timeout_seconds']),connector=aiohttp.TCPConnector(limit=32)) as session:
  async def wait_ready():
   for _ in range(600):
    if server.poll() is not None:raise RuntimeError('Server exited; inspect log')
    try:
     async with session.get(base+'/health') as response:
      if response.status==200:break
    except aiohttp.ClientError:pass
    await asyncio.sleep(1)
   else:raise RuntimeError('Startup timeout')
  await asyncio.wait_for(wait_ready(),timeout=spec['startup_timeout_seconds'])
  async def phase(name,policy,arrivals,horizon,role="measured"):
   async with session.post(base+'/phase',json=dict(phase=name,policy=policy)) as res:res.raise_for_status()
   epoch=time.monotonic()+.5;record=dict(name=name,policy=policy,role=role,epoch=epoch,horizon_seconds=horizon,arrivals=arrivals,client=[],complete=False);progress.append(record);atomic(root/'progress.json',progress)
   async def request(item):
    await asyncio.sleep(max(0,epoch+item['offset_seconds']-time.monotonic()));scheduled=epoch+item['offset_seconds'];submitted=time.monotonic();key=f"{name}--r{item['slot']:02d}";data=None
    async with session.post(base+'/generate',json=dict(key=key,id=item['id'],seed=item['seed'])) as res:
     res.raise_for_status()
     async for line in res.content:data=json.loads(line)
    if not data or not data['finished']:raise RuntimeError('Incomplete request '+key)
    row=dict(key=key,id=item['id'],seed=item['seed'],scheduled=scheduled,client_submitted=submitted,server_finished=data['monotonic'],latency_seconds=data['monotonic']-scheduled,injection_lag_seconds=submitted-scheduled,deadline=scheduled+item['relative_deadline_seconds']);record['client'].append(row);atomic(root/'progress.json',progress)
   await asyncio.wait_for(asyncio.gather(*(request(i) for i in arrivals)),timeout=max(i['offset_seconds'] for i in arrivals)+spec['phase_drain_timeout_seconds'])
   record['complete']=True;record['drained_at']=time.monotonic();record['injection_valid']=all(x['injection_lag_seconds']<=spec['max_injection_lag_seconds'] for x in record['client']);atomic(root/'progress.json',progress)
   if not record['injection_valid']:raise RuntimeError('Injection lag invalidates phase; preserve results, no automatic retry')
   return record
  trace=json.loads(args.trace.read_text());sha=hashlib.sha256((root/'trace.json').read_bytes()).hexdigest();atomic(root/'trace-freeze.json',dict(sha256=sha,frozen_before_probes_and_measured=True))
  async def probes():
   plan=json.loads((root/'probe-plan.json').read_text())
   for p in plan:await phase(p['name'],p['policy'],p['arrivals'],p['horizon_seconds'],role='probe')
   result=verify(root);atomic(root/'queue-gate.json',result)
  try:
   await asyncio.wait_for(probes(),timeout=spec['probe_total_timeout_seconds'])
  except BaseException as exc:
   atomic(root/'queue-gate.json',dict(passed=False,error=repr(exc)));raise
  for c in trace['conditions']:
   for policy in c['policy_order']:await phase(c['name']+'-'+policy,policy,c['arrivals'],c['horizon_seconds'])
  assert hashlib.sha256((root/'trace.json').read_bytes()).hexdigest()==sha
  atomic(root/'complete.json',dict(complete=True,stage=args.stage,phases=len(progress),planned_probes=7,planned_measured=36,completed_requests=sum(len(p['client']) for p in progress)))

def main():
 parser=argparse.ArgumentParser();parser.add_argument('--stage',choices=['pilot'],required=True);parser.add_argument('--out',type=Path,required=True);parser.add_argument('--trace',type=Path);args=parser.parse_args()
 if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Allocated Slurm GPU only')
 if args.stage=='pilot' and not args.trace:raise RuntimeError('Reviewed frozen trace required')
 args.out.mkdir(parents=True,exist_ok=False);(args.out/'requests').mkdir();os.environ['BURST_OUT']=str(args.out.resolve())
 atomic(args.out/'progress.json',[])
 if args.stage=='pilot':
  trace=json.loads(args.trace.read_text());validate_trace(json.loads((HERE/'spec.json').read_text()),trace);atomic(args.out/'trace.json',trace)
 spec=json.loads((HERE/'spec.json').read_text())
 spec['request_seed_base']=trace['seed_base']
 plan=json.loads((HERE/f"probe-r{trace['replicate']}.json").read_text())
 if plan!=probe_plan(spec,ranked_ids(spec['selection_salt'])[:4]):
  raise ValueError('Engineering plan differs from frozen recipe')
 atomic(args.out/'probe-plan.json',plan)
 atomic(args.out/'stage.json',dict(stage='engine-entry',replicate=trace['replicate'],planned=43,probes=7,measured=36))
 from evidence import snapshot
 snapshot(args.out)
 with (args.out/'server.log').open('w') as log:
  server=subprocess.Popen([sys.executable,'-B','-u',str(HERE/'server.py')],stdout=log,stderr=log)
  try:asyncio.run(run(args,server))
  except BaseException as exc:atomic(args.out/'failure.json',dict(error=repr(exc)));raise
  finally:
   server.terminate()
   try:server.wait(timeout=20)
   except subprocess.TimeoutExpired:server.kill();server.wait()
if __name__=='__main__':main()
