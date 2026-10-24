"""One staged job: exposed calibration and four matched reserved phases; no retries."""
import asyncio
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

HERE=Path(__file__).resolve().parent
REPO=HERE.parents[1]
sys.path.insert(0,str(REPO/'week4/step1/admission-control'))
import bootstrap
from execution import digest,trace_for,source_path
import aiohttp

ROOT=Path(os.environ['BURST_OUT'])
BASE='http://127.0.0.1:'+os.environ['BUDGET_PORT']
START=time.monotonic()

def dump(name,value):
    path=ROOT/name;tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.replace(path)


async def run(server,plan,shard,condition):
    phases=[]
    timeout=aiohttp.ClientTimeout(total=plan['budget']['phase_seconds']+60,connect=10)
    async with aiohttp.ClientSession(timeout=timeout,connector=aiohttp.TCPConnector(limit=20)) as session:
        until=time.monotonic()+plan['budget']['startup_seconds']
        while time.monotonic()<until:
            if server.poll() is not None:raise RuntimeError('Server exited before readiness')
            try:
                async with session.get(BASE+'/health') as response:
                    if response.status==200:break
            except (aiohttp.ClientError,asyncio.TimeoutError):pass
            await asyncio.sleep(1)
        else:raise TimeoutError('Saved engine startup allowance exceeded')

        async def phase(name,policy,arrivals,block=None):
            for _ in range(40):
                async with session.get(BASE+'/health') as response:
                    response.raise_for_status();health=await response.json()
                if not health['active']:break
                await asyncio.sleep(.5)
            else:raise RuntimeError('Previous phase did not drain')
            async with session.post(BASE+'/phase',json=dict(phase=name,policy=policy)) as response:response.raise_for_status()
            epoch=time.monotonic()+.5
            record=dict(phase=name,policy=policy,block=block,epoch=epoch,arrivals=arrivals,
                        completed=False,client=[],clock_domain='client.monotonic')
            phases.append(record);dump('progress.json',phases)
            async def request(item):
                key=f"{name}-{item['index']:03d}";scheduled=epoch+item['offset_seconds']
                await asyncio.sleep(max(0,scheduled-time.monotonic()))
                submitted=time.monotonic()
                row=dict(key=key,index=item['index'],scheduled=scheduled,client_submitted=submitted,
                         injection_lag_ms=1000*(submitted-scheduled),status='pending')
                try:
                    async with session.post(BASE+'/generate',json=dict(key=key,index=item['index'])) as response:
                        response.raise_for_status();first=None
                        async for line in response.content:
                            data=json.loads(line)
                            if first is None and data['tokens']:first=time.monotonic()
                            if data['finished']:
                                row.update(status='terminal',client_first=first,client_finished=time.monotonic(),
                                    tokens=data['tokens'],server_finished=data['monotonic'],finish_reason=data['finish_reason'])
                                return row
                        raise RuntimeError('No terminal response')
                except asyncio.CancelledError:
                    row.update(status='cancelled',client_failed=time.monotonic());raise
                except Exception as exc:
                    row.update(status='error',client_failed=time.monotonic(),error=type(exc).__name__)
                    return row
                finally:
                    record['client'].append(row);dump('progress.json',phases)
            await asyncio.wait_for(asyncio.gather(*(request(r) for r in arrivals)),timeout=plan['budget']['phase_seconds'])
            record.update(completed=True,finished=time.monotonic());dump('progress.json',phases)
            # Failure is kept; stop this job rather than silently rolling into a new phase.
            if any(r['status']!='terminal' for r in record['client']):raise RuntimeError('Infrastructure/client failure in saved phase')
            return record

        calibration=await phase('calib','full',[dict(index=i,offset_seconds=0) for i in plan['calibration']['indices']])
        cap_events=[json.loads(l) for l in (ROOT/'worker.jsonl').read_text().splitlines()]
        if any(e['event'] in ('thinking_cap','answer_cap') and e.get('key','').startswith('calib-') for e in cap_events):
            raise RuntimeError('Capped calibration: preserve, do not derive trace')
        for row in calibration['client']:
            raw=json.loads((ROOT/'requests'/f"{row['key']}.json").read_text())
            if raw['close_id'] not in raw['token_ids'] or raw['token_ids'][-1]!=raw['eos_id']:
                raise RuntimeError('Calibration lacks normal closed-thinking final')
        trace=trace_for(plan,shard,condition,calibration,time.monotonic())
        span=max(r['offset_seconds'] for r in trace['arrivals_by_block'][0])
        estimate=4*(span+8*trace['unit_seconds'])+600
        remaining=plan['budget']['driver_minutes']*60-(time.monotonic()-START)
        dump('runtime-fit.json',dict(estimated_remaining_seconds=estimate,remaining_driver_seconds=remaining,passed=estimate<=remaining))
        if estimate>remaining:raise RuntimeError('Trace cannot fit remaining allocation; no reserved inference started')
        dump('trace.json',trace);trace_sha=digest(ROOT/'trace.json')
        dump('trace-freeze.json',dict(sha256=trace_sha,plan_sha256=digest(ROOT/'plan.json'),
            frozen_before_measured=True,frozen_monotonic=trace['frozen_monotonic']))
        # Append-only exposure mark precedes each reserved phase, including failed attempts.
        for block,order in enumerate(plan['orders']):
            for policy in order:
                if not (ROOT/'exposure-started.json').exists():dump('exposure-started.json',dict(shard=shard,condition=condition,
                    indices=plan['sample']['shards'][shard]['indices'],first_measured_phase='b0-admission',
                    note='Reserved cohort considered exposed from first submission attempt onward'))
                await phase(f'b{block}-{policy}',policy,trace['arrivals_by_block'][block],block)
        assert digest(ROOT/'trace.json')==trace_sha
        dump('run-complete.json',dict(complete=True,shard=shard,condition=condition,trace_sha256=trace_sha,
            plan_sha256=digest(ROOT/'plan.json'),phases=phases,calibration_requests=2,measured_requests=48))


if __name__=='__main__':
    shard=int(os.environ['VALIDATION_SHARD']);condition=os.environ['VALIDATION_CONDITION']
    plan=json.loads((ROOT/'plan.json').read_text());lock=json.loads((HERE/'source-lock.json').read_text())
    assert condition in plan['conditions'] and shard in [0,1]
    for name,expected in lock.items():
        source=source_path(REPO,bootstrap.LEGACY,name)
        if digest(source)!=expected:raise RuntimeError('Source mismatch: '+name)
        target=ROOT/'sources'/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)
    expected=json.loads((ROOT/'candidate-lock.json').read_text())['files']
    assert all(lock[name]==sha for name,sha in expected.items())
    for name in ['vllm','torch','transformers']:
        if metadata.version(name).split('+')[0]!=plan['engine'][name]:raise RuntimeError('Runtime mismatch: '+name)
    dump('manifest.json',dict(job=os.getenv('SLURM_JOB_ID'),source_commit=os.getenv('VALIDATION_SOURCE_COMMIT'),shard=shard,condition=condition,sources=lock,
        versions={n:metadata.version(n) for n in ['vllm','torch','transformers','aiohttp','fastapi']},
        input_hashes={n:digest(ROOT/n) for n in ['plan.json','candidate-lock.json','spec.json','problems100.json',
                    'stage3-protocol.json','dataset-manifest.json','source-state.json','exposure-audit.json']},
        model=plan['engine']['model'],model_revision=plan['engine']['model_revision'],
        engine=plan['engine'],timing='Client scheduled-arrival to terminal receipt; same-host server diagnostic clocks only'))
    with (ROOT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-u',str(REPO/'week4/step1/admission-control/w4_server.py')],stdout=log,stderr=subprocess.STDOUT)
        try:asyncio.run(run(server,plan,shard,condition))
        except BaseException as exc:
            dump('run-failed.json',dict(error=type(exc).__name__,message=str(exc),elapsed_seconds=time.monotonic()-START));raise
        finally:
            server.terminate()
            try:server.wait(timeout=30)
            except subprocess.TimeoutExpired:server.kill();server.wait()
