"""One immutable trace, four drained phases, no retries or quality selection."""
import bootstrap
import asyncio
import hashlib
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

import aiohttp

ROOT = Path(os.environ['BURST_OUT'])
BASE = f"http://127.0.0.1:{os.environ['BUDGET_PORT']}"


def dump(name, value):
    target = ROOT / name
    temporary = target.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2)+'\n')
    temporary.replace(target)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


async def run(server, spec):
    phases = []
    dump('trace.json', dict(arrivals=spec['arrivals'], order=spec['policy_order'],
                            kind='mechanical smoke; no quality estimates'))
    trace_hash = digest(ROOT/'trace.json')
    dump('trace-freeze.json', dict(sha256=trace_hash, frozen_before_requests=True))
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=spec['limits']['phase_timeout_seconds']+60, connect=10),
                                     connector=aiohttp.TCPConnector(limit=16)) as session:
        startup_seconds = spec['limits']['startup_timeout_seconds']
        startup_deadline = time.monotonic() + startup_seconds
        while time.monotonic() < startup_deadline:
            if server.poll() is not None:
                raise RuntimeError('Server exited; inspect server.log')
            try:
                async with session.get(BASE+'/health') as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(1)
        else:
            raise TimeoutError(f'Startup exceeded {startup_seconds} seconds')

        for policy in spec['policy_order']:
            async with session.post(BASE+'/phase', json=dict(phase=policy, policy=policy)) as response:
                response.raise_for_status()
            epoch = time.monotonic()+0.5
            phase = dict(policy=policy, epoch=epoch, completed=False, client=[])
            phases.append(phase)
            dump('progress.json', phases)

            async def request(item):
                key = f"{policy}-{item['index']:02d}"
                scheduled = epoch+item['offset_seconds']
                await asyncio.sleep(max(0, scheduled-time.monotonic()))
                submitted = time.monotonic()
                record = dict(key=key, index=item['index'], scheduled=scheduled,
                              client_submitted=submitted, clock_domain='client.monotonic',
                              injection_lag_ms=1000*(submitted-scheduled))
                try:
                    async with session.post(BASE+'/generate', json=dict(key=key,index=item['index'])) as response:
                        response.raise_for_status()
                        first = None
                        async for line in response.content:
                            data = json.loads(line)
                            if first is None and data['tokens']:
                                first = time.monotonic()
                            if data['finished']:
                                record.update(client_first=first, client_finished=time.monotonic(),
                                              tokens=data['tokens'], finish_reason=data['finish_reason'],
                                              status='terminal')
                                break
                        else:
                            raise RuntimeError('Stream ended without terminal record')
                except BaseException as exc:
                    record.update(status='error', error=type(exc).__name__+': '+str(exc))
                    raise
                finally:
                    phase['client'].append(record)
                    dump('progress.json', phases)

            await asyncio.wait_for(asyncio.gather(*(request(item) for item in spec['arrivals'])),
                                   timeout=spec['limits']['phase_timeout_seconds'])
            phase.update(completed=True, finished=time.monotonic())
            dump('progress.json', phases)
        if digest(ROOT/'trace.json') != trace_hash:
            raise RuntimeError('Frozen trace changed')
        dump('run-complete.json', dict(complete=True, requests=sum(len(p['client']) for p in phases),
                                      trace_sha256=trace_hash, phases=phases))


if __name__ == '__main__':
    here = Path(__file__).resolve().parent
    spec = json.loads((ROOT/'spec.json').read_text())
    if metadata.version('vllm') != spec['vllm']:
        raise RuntimeError('Use the pinned vLLM runtime')
    files = [p for p in here.glob('*.py') if not p.name.startswith('.')]
    files += [here/'spec.json', here/'run_smoke.sbatch']
    source_paths = {str(p.relative_to(bootstrap.REPO)): p for p in files}
    source_paths.update({f'week3/larb/burst-policy/{name}': bootstrap.LEGACY/'burst-policy'/name
                         for name in ['adapter.py','policy.py']})
    source_paths['week3/larb/serving-proof/control.py'] = bootstrap.LEGACY/'serving-proof/control.py'
    sources = {name: digest(p) for name,p in source_paths.items()}
    lock = json.loads((here/'source-lock.json').read_text())
    if sources != lock:
        raise RuntimeError('Executed sources differ from the preflight source lock')
    for name, path in source_paths.items():
        target = ROOT/'sources'/name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    dump('manifest.json', dict(python=platform.python_version(),job=os.getenv('SLURM_JOB_ID'),
        hostname=platform.node(), versions={p:metadata.version(p) for p in
            ['vllm','torch','transformers','aiohttp','fastapi']}, sources=sources,
        input_hashes={name:digest(ROOT/name) for name in
            ['spec.json','problems100.json','stage3-protocol.json']},
        model_path=os.environ['BUDGET_MODEL_PATH'],
        clocks='All processes on one allocated host; client timing stays on client clock',
        quality_claim=False))
    with (ROOT/'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable,'-u',str(here/'w4_server.py')],
                                  stdout=log, stderr=subprocess.STDOUT)
        try:
            asyncio.run(run(server, spec))
        except BaseException as exc:
            dump('run-failed.json', dict(error=type(exc).__name__+': '+str(exc)))
            raise
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
