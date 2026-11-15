"""One outcome-blind semantic recovery attempt for the frozen case."""
import fcntl
import json
from pathlib import Path
import sys
import time
from urllib.request import Request, urlopen

from read_forecasts import HERE, body, digest, read
from resume_forecasts import atomic, check

CASE = 'case-169'


def recover(url, root, job, original_sha):
    cfg = read(HERE/'reader-config.json')
    prompt = (HERE/'PROMPT.txt').read_text()
    packets = read(HERE/'packets.json')
    with (root/'writer.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        original = root/f'{CASE}-invalid-7013461.json'
        assert digest(original) == original_sha
        assert read(root/'engineering-failure.json')['case_id'] == CASE
        assert not (root/'forecast-seal.json').exists()
        reader_lock = root/'reader-lock.json'
        for name, expected in read(reader_lock)['files'].items():
            assert digest((root if name=='synthetic.jsonl' else HERE)/name) == expected
        assert read(root/'manifest.json')['release_sha256'] == digest(HERE/'collection-lock.json')
        calls = root/'calls'
        missing = [k for k in packets if not (calls/f'{k}.json').exists()]
        assert len(packets)==174 and missing==[CASE]

        def verify(case, entry):
            assert entry['case_id']==case and entry['request']==body(packets[case],prompt,cfg)
            return dict(case_id=case,**check(entry['raw'],cfg),usage=entry['raw']['usage'],
                        wall_seconds=entry['wall_seconds'])

        records = {k:verify(k,read(calls/f'{k}.json')) for k in packets if k!=CASE}
        request = read(original)['request']
        assert request == body(packets[CASE],prompt,cfg)
        attempt = root/'case-169-recovery-v1'
        attempt.mkdir()  # Exclusive and persistent, including transport failures.
        atomic(attempt/'attempt.json',dict(case=CASE,job=job,original_sha256=original_sha,request=request))
        start=time.monotonic()
        try:
            with urlopen(Request(url,data=json.dumps(request).encode(),
                                 headers={'Content-Type':'application/json'}),timeout=600) as response:
                raw=json.load(response)
            entry=dict(case_id=CASE,request=request,raw=raw,job=job,wall_seconds=time.monotonic()-start)
            atomic(attempt/'response.json',entry)
            records[CASE]=verify(CASE,entry)
        except Exception as exc:
            atomic(attempt/'status.json',dict(valid=False,error=repr(exc)))
            raise
        atomic(calls/f'{CASE}.json',entry)
        forecasts=root/'forecasts.jsonl'
        temp=forecasts.with_suffix('.tmp')
        temp.write_text(''.join(json.dumps(records[k],ensure_ascii=False)+'\n' for k in packets))
        temp.replace(forecasts)
        raw_lock=root/'raw-lock.json'
        atomic(raw_lock,{k:digest(calls/f'{k}.json') for k in packets})
        atomic(root/'forecast-seal.json',dict(forecast_sha256=digest(forecasts),
            reader_lock_sha256=digest(reader_lock),raw_lock_sha256=digest(raw_lock)))
        atomic(attempt/'status.json',dict(valid=True,sealed=True,count=len(records)))


if __name__=='__main__':
    recover(sys.argv[1],Path(sys.argv[2]),sys.argv[3],sys.argv[4])
