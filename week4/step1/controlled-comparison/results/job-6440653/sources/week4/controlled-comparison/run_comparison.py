"""Calibrate once, freeze one trace, then execute two matched four-policy blocks."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'admission-control'))
import bootstrap
from run_smoke import dump, digest, ROOT, BASE
import asyncio
import importlib.metadata as metadata
import json
import os
import platform
import shutil
import subprocess
import time

import aiohttp


def freeze_trace(spec, calibration):
    if len(calibration['client'])!=2 or any(r['status']!='terminal' for r in calibration['client']):
        raise RuntimeError('Calibration incomplete; do not invent a trace')
    durations=[r['client_finished']-r['scheduled'] for r in calibration['client']]
    rule=spec['calibration_rule']
    burst=rule['burst_fraction_of_min_latency']*min(durations)
    deadline=max(rule['minimum_deadline_seconds'],rule['deadline_multiple_of_max_latency']*max(durations))
    arrivals=[dict(index=i,offset_seconds=0 if i<2 else burst+(i-2)*.05) for i in range(12)]
    return dict(arrivals=arrivals,relative_deadline_seconds=deadline,burst_at_seconds=burst,
                observation_horizon_seconds=max(r['offset_seconds']+deadline for r in arrivals),
                calibration_latencies_seconds=durations,orders=spec['policy_orders'],
                frozen_monotonic=time.monotonic(),clock_domain='client.monotonic')


async def run(server,spec):
    phases=[]
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
            total=spec['limits']['phase_timeout_seconds']+60,connect=10),
            connector=aiohttp.TCPConnector(limit=20)) as session:
        until=time.monotonic()+spec['limits']['startup_timeout_seconds']
        while time.monotonic()<until:
            if server.poll() is not None:
                raise RuntimeError('Server exited; inspect server.log')
            try:
                async with session.get(BASE+'/health') as response:
                    if response.status==200:
                        break
            except (aiohttp.ClientError,asyncio.TimeoutError):
                pass
            await asyncio.sleep(1)
        else:
            raise TimeoutError('Engine startup exceeded saved allowance')

        async def phase(name,policy,arrivals,block=None):
            for _ in range(20):
                async with session.get(BASE+'/health') as response:
                    health=await response.json()
                if not health['active']:
                    break
                await asyncio.sleep(.5)
            else:
                raise RuntimeError('Prior phase did not drain')
            async with session.post(BASE+'/phase',json=dict(phase=name,policy=policy)) as response:
                response.raise_for_status()
            epoch=time.monotonic()+.5
            record=dict(phase=name,policy=policy,block=block,epoch=epoch,arrivals=arrivals,
                        completed=False,client=[],clock_domain='client.monotonic')
            phases.append(record)
            dump('progress.json',phases)

            async def request(item):
                key=f"{name}-{item['index']:02d}"
                scheduled=epoch+item['offset_seconds']
                await asyncio.sleep(max(0,scheduled-time.monotonic()))
                submitted=time.monotonic()
                row=dict(key=key,index=item['index'],scheduled=scheduled,client_submitted=submitted,
                         injection_lag_ms=1000*(submitted-scheduled),status='pending')
                try:
                    async with session.post(BASE+'/generate',json=dict(key=key,index=item['index'])) as response:
                        response.raise_for_status()
                        first=None
                        async for line in response.content:
                            data=json.loads(line)
                            if first is None and data['tokens']:
                                first=time.monotonic()
                            if data['finished']:
                                row.update(status='terminal',client_first=first,
                                           client_finished=time.monotonic(),tokens=data['tokens'],
                                           server_finished=data['monotonic'],finish_reason=data['finish_reason'])
                                return row
                        raise RuntimeError('Stream ended without a terminal record')
                except asyncio.CancelledError:
                    row.update(status='cancelled',client_failed=time.monotonic())
                    raise
                except Exception as exc:
                    row.update(status='error',client_failed=time.monotonic(),
                               error=type(exc).__name__+': '+str(exc))
                    return row
                finally:
                    record['client'].append(row)
                    dump('progress.json',phases)

            await asyncio.wait_for(asyncio.gather(*(request(item) for item in arrivals)),
                                   timeout=spec['limits']['phase_timeout_seconds'])
            record.update(completed=True,finished=time.monotonic())
            dump('progress.json',phases)
            return record

        calibration=await phase('calib','full',[dict(index=i,offset_seconds=0)
                                               for i in spec['calibration_indices']])
        cap_events=[json.loads(line) for line in (ROOT/'worker.jsonl').read_text().splitlines()]
        if any(e['event'] in ('thinking_cap','answer_cap') and e.get('key','').startswith('calib-')
               for e in cap_events):
            raise RuntimeError('Calibration hit a cap; preserve and diagnose before deriving trace')
        for row in calibration['client']:
            if row['status']!='terminal':
                raise RuntimeError('Calibration did not complete')
            raw=json.loads((ROOT/'requests'/f"{row['key']}.json").read_text())
            if raw['close_id'] not in raw['token_ids'] or raw['token_ids'][-1]!=raw['eos_id']:
                raise RuntimeError('Calibration lacks a normal closed-thinking final')
        trace=freeze_trace(spec,calibration)
        dump('trace.json',trace)
        trace_sha=digest(ROOT/'trace.json')
        dump('trace-freeze.json',dict(sha256=trace_sha,frozen_before_measured=True,
                                     frozen_monotonic=trace['frozen_monotonic']))
        for block,order in enumerate(spec['policy_orders']):
            for policy in order:
                await phase(f'b{block}-{policy}',policy,trace['arrivals'],block)
        if digest(ROOT/'trace.json')!=trace_sha:
            raise RuntimeError('Frozen trace changed')
        dump('run-complete.json',dict(complete=True,trace_sha256=trace_sha,phases=phases,
            calibration_requests=2,measured_requests=sum(len(p['client']) for p in phases if p['block'] is not None)))


if __name__=='__main__':
    here=Path(__file__).resolve().parent
    spec=json.loads((ROOT/'spec.json').read_text())
    lock=json.loads((here/'source-lock.json').read_text())
    for name,expected in lock.items():
        source=(bootstrap.LEGACY/name.removeprefix('week3/larb/')
                if name.startswith('week3/larb/') else bootstrap.REPO/name)
        if digest(source)!=expected:
            raise RuntimeError('Source changed: '+name)
        target=ROOT/'sources'/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copy2(source,target)
    if metadata.version('vllm')!=spec['vllm']:
        raise RuntimeError('Wrong vLLM runtime')
    dump('manifest.json',dict(job=os.getenv('SLURM_JOB_ID'),hostname=platform.node(),
        python=platform.python_version(),sources=lock,
        versions={p:metadata.version(p) for p in ['vllm','torch','transformers','aiohttp','fastapi']},
        input_hashes={n:digest(ROOT/n) for n in ['spec.json','problems100.json','stage3-protocol.json','gate.json','PLAN.md','source-state.json']},
        model_path=os.environ['BUDGET_MODEL_PATH'],engine=dict(max_num_seqs=2,dtype='bfloat16',
            max_model_len=24576,max_num_batched_tokens=2048,enforce_eager=True,prefix_caching=False),
        timing='Primary timestamps share the replay client monotonic clock'))
    with (ROOT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-u',str(bootstrap.REPO/'week4/admission-control/w4_server.py')],
                                 stdout=log,stderr=subprocess.STDOUT)
        try:
            asyncio.run(run(server,spec))
        except BaseException as exc:
            dump('run-failed.json',dict(error=type(exc).__name__+': '+str(exc)))
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=30)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
