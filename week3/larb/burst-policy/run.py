"""One engine, two calibration requests, then one frozen trace / three policies."""
import asyncio
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import aiohttp

ROOT=Path(os.environ['BURST_OUT'])
BASE=f"http://127.0.0.1:{os.environ['BUDGET_PORT']}"


def dump(name,value):
    target=ROOT/name
    temp=target.with_suffix('.tmp')
    temp.write_text(json.dumps(value,indent=2)+'\n')
    temp.replace(target)


async def run(server):
    spec=json.loads((ROOT/'spec.json').read_text())
    phases=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=2800),
            connector=aiohttp.TCPConnector(limit=30),read_bufsize=1024*1024) as session:
        for _ in range(600):
            if server.poll() is not None:
                raise RuntimeError('Server exited; inspect server.log')
            try:
                async with session.get(BASE+'/health') as response:
                    if response.status==200:
                        break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(1)
        else:
            raise TimeoutError('Startup exceeded ten minutes')

        async def phase(name,policy,arrivals):
            async with session.post(BASE+'/phase',json=dict(phase=name,policy=policy)) as response:
                response.raise_for_status()
            epoch=time.monotonic()+0.5
            phase_record=dict(phase=name,policy=policy,epoch=epoch,arrivals=arrivals,
                              completed=False,client=[])
            phases.append(phase_record)
            dump('progress.json',phases)

            async def request(item):
                await asyncio.sleep(max(0,epoch+item['offset_seconds']-time.monotonic()))
                scheduled=epoch+item['offset_seconds']
                submitted=time.monotonic()
                key=f"{name}-{item['index']:02d}"
                first=None
                async with session.post(BASE+'/generate',json=dict(key=key,index=item['index'])) as response:
                    response.raise_for_status()
                    async for line in response.content:
                        data=json.loads(line)
                        if first is None:
                            first=time.monotonic()
                        if data['finished']:
                            row=dict(key=key,index=item['index'],scheduled=scheduled,
                                client_submitted=submitted,client_first=first,
                                client_finished=time.monotonic(),server_finished=data['monotonic'],
                                tokens=data['tokens'],injection_lag_ms=1000*(submitted-scheduled))
                            phase_record['client'].append(row)
                            dump('progress.json',phases)
                            return row
                raise RuntimeError('Stream ended before normal terminal record: '+key)
            await asyncio.wait_for(asyncio.gather(*(request(a) for a in arrivals)),timeout=1800)
            phase_record['completed']=True
            phase_record['finished']=time.monotonic()
            dump('progress.json',phases)
            return phase_record

        calibration=await phase('calib','full',[dict(index=i,offset_seconds=0) for i in [0,2]])
        durations=[r['server_finished']-r['scheduled'] for r in calibration['client']]
        burst_at=0.25*min(durations)
        deadline=2*max(durations)
        arrivals=[dict(index=i,offset_seconds=0 if i<2 else burst_at+(i-2)*0.05)
                  for i in range(12)]
        trace=dict(calibration_indices=[0,2],calibration_latencies_seconds=durations,
            burst_at_seconds=burst_at,relative_deadline_seconds=deadline,arrivals=arrivals,
            fixed_observation_horizon_seconds=arrivals[-1]['offset_seconds']+deadline,
            frozen_monotonic=time.monotonic(),order=spec['policy_order'])
        dump('trace.json',trace)
        # This trace is written exactly once, before any measured policy request.
        trace_sha=hashlib.sha256((ROOT/'trace.json').read_bytes()).hexdigest()
        dump('trace-freeze.json',dict(sha256=trace_sha,frozen_before_policies=True))
        for policy in spec['policy_order']:
            await asyncio.sleep(1)
            await phase(policy,policy,arrivals)
        assert hashlib.sha256((ROOT/'trace.json').read_bytes()).hexdigest()==trace_sha
        dump('run-complete.json',dict(complete=True,measured_attempts=36,
            calibration_attempts=2,trace_sha256=trace_sha,phases=phases))


if __name__=='__main__':
    here=Path(__file__).parent
    sources={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in here.glob('*.py')}
    control=here.parent/'serving-proof/control.py'
    sources['proof-control.py']=hashlib.sha256(control.read_bytes()).hexdigest()
    dump('manifest.json',dict(python=platform.python_version(),job=os.getenv('SLURM_JOB_ID'),
        versions={p:metadata.version(p) for p in ['vllm','torch','transformers','aiohttp','fastapi']},
        sources=sources,spec_sha256=hashlib.sha256((ROOT/'spec.json').read_bytes()).hexdigest(),
        model_path=os.environ['BUDGET_MODEL_PATH'],max_num_seqs=2,
        note='Instrumented eager vLLM pilot; one trace, one sampled response per problem/policy'))
    with (ROOT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-u',str(here/'server.py')],stdout=log,stderr=subprocess.STDOUT)
        try:
            asyncio.run(run(server))
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill();server.wait()
