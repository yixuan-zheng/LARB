"""Stateless forecasts from the pinned local vLLM server."""
import argparse
import concurrent.futures
import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen

HERE = Path(__file__).resolve().parent
KEYS = ('ww', 'wc', 'cw', 'cc')
SCHEMA = dict(type='object', additionalProperties=False, required=[*KEYS, 'explanation'],
              properties={**{name: dict(type='integer', minimum=0, maximum=100) for name in KEYS},
                          'explanation': dict(type='string', minLength=1)})
SYNTHETIC = {
    'synthetic-question': dict(question='What is 6 times 4? Give the final integer.', prefix=''),
    'synthetic-prefix': dict(question='What is 6 times 4? Give the final integer.',
                             prefix='I wrote 26, but six groups of four are 4+4+4+4+4+4. I should add them.'),
}


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def body(packet, prompt, config):
    if set(packet) != {'question', 'prefix'}:
        raise ValueError('Unexpected packet fields')
    return dict(
        model=config['model'], max_tokens=config['max_tokens'], temperature=config['temperature'],
        thinking_token_budget=config['thinking_token_budget'],
        chat_template_kwargs={'reasoning_effort': config['reasoning_effort']},
        messages=[dict(role='system', content=prompt), dict(role='user', content=json.dumps(packet, ensure_ascii=False))],
        response_format=dict(type='json_schema', json_schema=dict(name='forecast', strict=True, schema=SCHEMA)),
    )


def parse(response):
    choice, = response['choices']
    if choice['finish_reason'] != 'stop':
        raise ValueError(f"Reader finish reason: {choice['finish_reason']}")
    record = json.loads(choice['message']['content'])
    if set(record) != {*KEYS, 'explanation'}:
        raise ValueError('Unexpected forecast fields')
    values = [record[k] for k in KEYS]
    if not all(type(x) is int and 0 <= x <= 100 for x in values) or sum(values) != 100:
        raise ValueError('Expected four integer percentages summing to 100')
    if not isinstance(record['explanation'], str) or not record['explanation'].strip():
        raise ValueError('Missing explanation')
    return record


def collect(packets, url, config, prompt, destination):
    def forecast(entry):
        case, packet = entry
        request = Request(url, data=json.dumps(body(packet, prompt, config)).encode(),
                          headers={'Content-Type': 'application/json'})
        start = time.monotonic()
        with urlopen(request, timeout=600) as result:
            response = json.load(result)
        try:
            record = parse(response)
        except Exception:
            path = destination.parent / f'{case}-invalid-response.json'
            path.write_text(json.dumps(response, indent=2)+'\n')
            raise
        return dict(case_id=case, **record, usage=response.get('usage'), wall_seconds=time.monotonic()-start)

    with destination.open('x') as output, concurrent.futures.ThreadPoolExecutor(config['concurrency']) as pool:
        for index, record in enumerate(pool.map(forecast, packets.items()), 1):
            output.write(json.dumps(record, ensure_ascii=False)+'\n')
            output.flush()
            if index % 10 == 0 or index == len(packets):
                print(f'{destination.name}: {index}/{len(packets)}', flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('url')
    parser.add_argument('out', type=Path)
    parser.add_argument('--smoke-only', action='store_true')
    args = parser.parse_args()
    config = read(HERE/'reader-config.json')
    prompt = (HERE/'PROMPT.txt').read_text()
    args.out.mkdir(exist_ok=False)
    collect(SYNTHETIC, args.url, config, prompt, args.out/'synthetic.jsonl')
    if args.smoke_only:
        path = args.out/'smoke.jsonl'
        collect(read(HERE/'smoke-packets.json'), args.url, config, prompt, path)
        records = [json.loads(line) for line in path.read_text().splitlines()]
        assert len(records) == 8
        assert all(r['usage']['completion_tokens_details']['reasoning_tokens'] <=
                   config['thinking_token_budget'] + 8 for r in records)
        (args.out/'smoke-pass.json').write_text(json.dumps(dict(
            cases=len(records), smoke_sha256=digest(path),
            config_sha256=digest(HERE/'reader-config.json'), prompt_sha256=digest(HERE/'PROMPT.txt'),
            runner_sha256=digest(HERE/'read_forecasts.py')), indent=2)+'\n')
        return
    files = {name: digest(HERE/name) for name in ('reader-config.json', 'PROMPT.txt', 'packets.json', 'read_forecasts.py', 'run.sbatch')}
    files['synthetic.jsonl'] = digest(args.out/'synthetic.jsonl')
    lock = args.out/'reader-lock.json'
    lock.write_text(json.dumps(dict(files=files), indent=2)+'\n')
    print('Synthetic forecasts passed; reader frozen.', flush=True)
    forecasts = args.out/'forecasts.jsonl'
    collect(read(HERE/'packets.json'), args.url, config, prompt, forecasts)
    (args.out/'forecast-seal.json').write_text(json.dumps(dict(
        forecast_sha256=digest(forecasts), reader_lock_sha256=digest(lock)), indent=2)+'\n')


if __name__ == '__main__':
    main()
