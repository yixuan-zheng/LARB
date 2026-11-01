"""Read-only access to saved Week 4 run directories."""
import gzip
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ([ROOT / 'week4/baseline-controls/results' / j for j in ('job-6512259', 'job-6512260')]
        + [ROOT / 'week4/reserved-validation/results' / f'job-64819{n}' for n in (23, 75, 76, 77, 78, 79)])


def jsonl(path):
    opener = gzip.open if path.suffix == '.gz' else open
    with opener(path, 'rt') as f:
        for line in f:
            yield json.loads(line)


def load_run(run):
    trace = json.loads((run / 'trace.json').read_text())
    # measured phases only; calibration has block None
    phases = [p for p in json.loads((run / 'progress.json').read_text()) if p['block'] is not None]
    records = {p.stem: json.loads(p.read_text()) for p in (run / 'requests').glob('*.json')}
    arrival = {e['key']: e['monotonic'] for e in jsonl(run / 'service.jsonl') if e['event'] == 'arrival'}
    graded = {g['key']: g for g in json.loads((run / 'analysis/graded.json').read_text())}
    D = trace['relative_deadline_seconds']
    deadline, policy = {}, {}
    for p in phases:
        for c in p['client']:
            # server-clock deadline; each difference stays inside one clock
            deadline[c['key']] = arrival[c['key']] + D - (c['client_submitted'] - c['scheduled'])
            policy[c['key']] = p['policy']
    return dict(name=run.name, condition=trace['condition'], D=D, records=records, graded=graded,
                worker=list(jsonl(run / 'worker.jsonl')), deadline=deadline, policy=policy)


def iter_steps(run):
    """(time, {key: computed tokens incl. prompt}, waiting keys in queue order) per scheduler step."""
    for e in jsonl(run / 'scheduler.jsonl.gz'):
        if e['event'] == 'step':
            yield e['monotonic'], {a['key']: a['computed_after'] for a in e['active']}, e['waiting']
