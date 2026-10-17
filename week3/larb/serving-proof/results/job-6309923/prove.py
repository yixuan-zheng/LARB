"""Run three actual overlapping HTTP requests, update budgets, verify evidence."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import aiohttp

ROOT = Path(os.environ['BUDGET_PROOF_DIR'])
BASE = f"http://127.0.0.1:{os.environ['BUDGET_PORT']}"


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, indent=2) + '\n')


async def main(server):
    latest = {}
    tasks = {}
    events = []
    problems = json.loads((ROOT / 'problems100.json').read_text())
    def event(kind, **data):
        events.append(dict(event=kind, monotonic=time.monotonic(), **data))

    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=1200),
                                     read_bufsize=1024 * 1024) as session:
        for _ in range(900):
            if server.poll() is not None:
                raise RuntimeError('Serving process exited; inspect server.log')
            try:
                async with session.get(BASE + '/health') as response:
                    if response.status == 200:
                        break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(1)
        else:
            raise TimeoutError('Server not ready within 15 minutes')

        async def consume(key, index):
            event('client_submit', key=key, index=index)
            async with session.post(BASE + '/generate', json=dict(key=key, index=index,
                    prompt=problems[index]['problem'] + '\nPlease put your final answer within \\boxed{}.')) as response:
                response.raise_for_status()
                async for line in response.content:
                    data = json.loads(line)
                    latest[key] = data
                    if data['finished']:
                        event('client_finished', key=key, tokens=len(data['token_ids']))

        async def wait_for(predicate):
            begin = time.monotonic()
            while not predicate():
                for task in tasks.values():
                    if task.done() and task.exception():
                        raise task.exception()
                if time.monotonic() - begin > 300:
                    raise TimeoutError('Required concurrent-serving event did not occur')
                await asyncio.sleep(0.01)

        async def update(key, budget):
            event('client_budget_update', key=key, budget=budget,
                  tokens_seen=len(latest[key]['token_ids']), finished=latest[key]['finished'])
            assert not latest[key]['finished'], 'Update must occur before completion'
            async with session.post(BASE + f'/budget/{key}', json={'budget': budget}) as response:
                response.raise_for_status()
                return await response.json()

        tasks['A'] = asyncio.create_task(consume('A', 1))
        await wait_for(lambda: len(latest.get('A', {}).get('token_ids', [])) >= 128)
        tasks['B'] = asyncio.create_task(consume('B', 0))
        await wait_for(lambda: len(latest.get('B', {}).get('token_ids', [])) >= 64)
        tasks['C'] = asyncio.create_task(consume('C', 2))
        await wait_for(lambda: len(latest['A']['token_ids']) >= 512)
        await update('A', 512)
        # B is a natural-close control; the late command must not reopen thinking.
        await wait_for(lambda: '</think>' in latest.get('B', {}).get('text', ''))
        await update('B', 1)
        await asyncio.wait_for(asyncio.gather(*tasks.values()), timeout=600)
    write('client-events.json', events)


def verify():
    worker = [json.loads(line) for line in (ROOT / 'worker.jsonl').read_text().splitlines()]
    scheduler = [json.loads(line) for line in (ROOT / 'scheduler.jsonl').read_text().splitlines()]
    service = [json.loads(line) for line in (ROOT / 'service.jsonl').read_text().splitlines()]
    results = {key: json.loads((ROOT / f'{key}.json').read_text()) for key in 'ABC'}
    protocol = json.loads((ROOT / 'protocol.json').read_text())
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(os.environ['BUDGET_MODEL_PATH'])
    close = tok.convert_tokens_to_ids('</think>')
    opening = tok.convert_tokens_to_ids('<think>')
    cue = tok.encode(protocol['transition_text'], add_special_tokens=False)
    changes = [e for e in worker if e['event'] == 'budget_observed' and e['key'] == 'A']
    starts = [e for e in worker if e['event'] == 'cue_started' and e['key'] == 'A']
    checks = {}
    checks['A_update_observed_after_512_generated_tokens'] = len(changes) == 1 and changes[0]['accepted'] and changes[0]['tokens'] >= 512
    checks['A_forces_cue_after_update'] = len(starts) == 1 and starts[0]['monotonic'] >= changes[0]['monotonic']
    start = starts[0]['tokens'] if starts else -1
    ids = results['A']['token_ids']
    checks['A_exact_stage3_cue'] = ids[start:start + len(cue)] == cue
    checks['A_answer_continues_and_ends_normally'] = close in ids and len(ids) > ids.index(close) + 2 and results['A']['finish_reason'] == 'stop'
    checks['all_requests_finish_normally'] = all(r['finished'] and r['finish_reason'] == 'stop' for r in results.values())
    checks['no_forced_answer_cap_EOS'] = not any(e['event'] == 'answer_cap_forced' for e in worker)
    checks['no_reopened_thinking'] = all(close in r['token_ids'] and opening not in r['token_ids'][r['token_ids'].index(close)+1:] for r in results.values())
    checks['one_submission_each'] = all(sum(e['event'] == 'submitted' and e['key'] == k for e in service) == 1 for k in 'ABC')
    checks['one_worker_admission_each'] = all(sum(e['event'] == 'added' and e['key'] == k for e in worker) == 1 for k in 'ABC')
    checks['A_same_worker_output_object'] = len({e['output_object'] for e in worker if e.get('key') == 'A' and 'output_object' in e}) == 1
    checks['B_natural_close'] = any(e['event'] == 'thinking_closed' and e['key'] == 'B' and not e['forced'] for e in worker)
    checks['B_late_update_ignored'] = any(e['event'] == 'budget_observed' and e['key'] == 'B' and not e['accepted'] for e in worker)
    steps = [e for e in scheduler if e['event'] == 'step']
    # Internal engine IDs may include an engine-generated suffix; match prefixes.
    def identity(key):
        return next((k for k in 'ABC' if key == k or key.startswith(k + '-')), key)
    checks['A_and_B_actually_scheduled_together'] = any({'A','B'} <= {identity(r['key']) for r in e['active']} for e in steps)
    checks['C_waited_while_AB_active'] = any('C' in {identity(k) for k in e['waiting']} and {'A','B'} <= {identity(r['key']) for r in e['active']} for e in steps)
    checks['C_admitted_while_another_request_active'] = any('C' in {identity(r['key']) for r in e['active']} and len(e['active']) == 2 for e in steps)
    all_rows = [r for e in steps for r in e['active']]
    checks['no_preemptions'] = all(r['preemptions'] == 0 for r in all_rows)
    continuity = True
    histories = {}
    for row in all_rows:
        old = histories.get(row['key'])
        if old:
            continuity &= row['computed_before'] >= old['computed_after']
            continuity &= all(new[:len(previous)] == previous for previous, new in zip(old['blocks'], row['blocks']))
        histories[row['key']] = row
    checks['computed_tokens_monotonic_and_KV_blocks_retained'] = continuity
    checks['scheduler_samples_exist_before_and_after_A_change'] = bool(changes) and any(e['monotonic'] < changes[0]['monotonic'] and any(identity(r['key']) == 'A' for r in e['active']) for e in steps) and any(e['monotonic'] > changes[0]['monotonic'] and any(identity(r['key']) == 'A' for r in e['active']) for e in steps)
    write('validation.json', {'passed': all(checks.values()), 'checks': checks,
                             'forced_start': start, 'scheduler_steps': len(steps)})
    print(json.dumps(checks, indent=2), flush=True)
    assert all(checks.values()), 'Serving proof failed; inspect validation.json'


if __name__ == '__main__':
    ROOT.mkdir(exist_ok=True, parents=True)
    import importlib.metadata as metadata
    write('manifest.json', dict(python=platform.python_version(), job=os.getenv('SLURM_JOB_ID'),
        versions={p: metadata.version(p) for p in ['vllm','torch','transformers','fastapi','aiohttp']},
        sources={p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('*.py')},
        model_path=os.environ['BUDGET_MODEL_PATH'], max_num_seqs=2,
        note='Mechanism proof only; eager engine, file control polling, scheduler tracing; not a performance benchmark'))
    with (ROOT / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-u', str(Path(__file__).with_name('server.py'))], stdout=log, stderr=subprocess.STDOUT)
        try:
            asyncio.run(main(server))
            verify()
        finally:
            server.terminate()
            try:
                server.wait(timeout=20)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()
