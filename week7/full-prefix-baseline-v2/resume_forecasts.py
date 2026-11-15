"""Collect frozen requests with per-case raw commits and an all-or-nothing seal."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
from pathlib import Path
import time
from urllib.request import Request, urlopen

from read_forecasts import HERE, SYNTHETIC, body, digest, parse, read


def atomic(path, value):
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False)+'\n')
    tmp.replace(path)


def check(raw, config):
    record = parse(raw)
    usage = raw['usage']
    if (not 0 < usage['completion_tokens'] < config['max_tokens'] or
            not 0 <= usage['completion_tokens_details']['reasoning_tokens'] <= config['thinking_token_budget']+8):
        raise ValueError('Reader token usage outside the validated envelope')
    return record


def run(url, root, stop, job):
    config = read(HERE/'reader-config.json')
    prompt = (HERE/'PROMPT.txt').read_text()
    packets = read(HERE/'packets.json')
    assert len(packets) == 174 and sum(bool(p['prefix']) for p in packets.values()) == 115
    release = read(HERE/'collection-lock.json')
    for name, expected in release.items():
        assert digest(HERE/name) == expected, name
    root.mkdir(exist_ok=True)
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if (root/'engineering-failure.json').exists():
            raise ValueError('Previous engineering failure requires review')
        manifest = dict(release_sha256=digest(HERE/'collection-lock.json'), model=config)
        if (root/'manifest.json').exists():
            assert read(root/'manifest.json') == manifest
        else:
            atomic(root/'manifest.json', manifest)
        calls = root/'calls'
        calls.mkdir(exist_ok=True)
        started = time.monotonic()
        waves = []

        def collect(case, packet):
            assert case.isalnum() or all(c.isalnum() or c in '-_' for c in case)
            path = calls/f'{case}.json'
            request_body = body(packet, prompt, config)
            if path.exists():
                entry = read(path)
                assert entry['case_id'] == case and entry['request'] == request_body
                record = check(entry['raw'],config)
            else:
                request = Request(url, data=json.dumps(request_body).encode(),
                                  headers={'Content-Type':'application/json'})
                begin = time.monotonic()
                with urlopen(request,timeout=600) as result:
                    raw = json.load(result)
                entry = dict(case_id=case, request=request_body, raw=raw, job=job,
                             wall_seconds=time.monotonic()-begin)
                try:
                    record = check(raw,config)
                except (ValueError, TypeError, KeyError) as error:
                    atomic(root/f'{case}-invalid-{job}.json',entry)
                    atomic(root/'engineering-failure.json',dict(case_id=case,error=repr(error)))
                    raise
                atomic(path,entry)
            return dict(case_id=case,**record,usage=entry['raw']['usage'],wall_seconds=entry['wall_seconds'])

        def batch(items):
            begin = time.monotonic()
            with ThreadPoolExecutor(config['concurrency']) as pool:
                out = list(pool.map(lambda pair:collect(*pair),items))
            waves.append(dict(count=len(items),seconds=time.monotonic()-begin))
            return out

        def export(name, records):
            path = root/name
            content = ''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records)
            if path.exists():
                assert path.read_text() == content
            else:
                tmp = path.with_suffix('.tmp')
                tmp.write_text(content)
                tmp.replace(path)

        if time.time()+660 > stop:
            raise RuntimeError('Insufficient time after server startup')
        synthetic = batch(list(SYNTHETIC.items()))
        export('synthetic.jsonl',synthetic)
        files = {name:digest(HERE/name) for name in
                 ('reader-config.json','PROMPT.txt','packets.json','read_forecasts.py','run.sbatch',
                  'resume_forecasts.py','collect.sbatch','collection-lock.json')}
        files['synthetic.jsonl'] = digest(root/'synthetic.jsonl')
        reader_lock = root/'reader-lock.json'
        if reader_lock.exists():
            assert read(reader_lock) == dict(files=files)
        else:
            atomic(reader_lock,dict(files=files))
        pending = [(k,v) for k,v in packets.items() if not (calls/f'{k}.json').exists()]
        before = len(packets)-len(pending)
        # Verify old records before issuing any fresh real request.
        for case, packet in packets.items():
            if (calls/f'{case}.json').exists():
                collect(case,packet)
        for i in range(0,len(pending),config['concurrency']):
            if time.time()+660 > stop:
                break
            batch(pending[i:i+config['concurrency']])
            print(f'{before+min(i+config["concurrency"],len(pending))}/174 validated',flush=True)
        committed = sum((calls/f'{k}.json').exists() for k in packets)
        if committed == len(packets):
            records = [collect(k,v) for k,v in packets.items()]
            export('forecasts.jsonl',records)
            raw_lock = root/'raw-lock.json'
            atomic(raw_lock,{k:digest(calls/f'{k}.json') for k in packets})
            atomic(root/'forecast-seal.json',dict(forecast_sha256=digest(root/'forecasts.jsonl'),
                reader_lock_sha256=digest(reader_lock),raw_lock_sha256=digest(raw_lock)))
        metrics = dict(job=job, before=before, committed=committed, new=committed-before,
                       waves=waves, collection_seconds=time.monotonic()-started,
                       sealed=committed==len(packets))
        atomic(root/f'progress-{job}.json',metrics)
        print(metrics,flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('url')
    p.add_argument('root',type=Path)
    p.add_argument('stop',type=int)
    p.add_argument('job')
    a=p.parse_args()
    run(a.url,a.root,a.stop,a.job)
