"""Timing estimates for the shadow rule -> estimates.json.

tau      seconds per decode step with two requests decoding (= s/token per request)
answer   seconds from the forced cue starting to the finished answer
service  seconds a fixed-2,048 request holds its slot (admitted -> finished)
totals   week 3 stage 3 full-thinking lengths (lengths only, not correctness)
"""
import csv
import json
import statistics
from pathlib import Path

from records import ROOT, RUNS, iter_steps, load_run

OUT = Path(__file__).with_name('estimates.json')
STAGE3 = ROOT / 'week3/larb/stage3/analysis/per-problem.csv'


def decode_step_times(run):
    times, prev = [], None
    for t, active, _ in iter_steps(run):
        if (prev and len(active) == 2 and active.keys() == prev[1].keys()
                and all(active[k] - prev[1][k] == 1 for k in active)):
            times.append(t - prev[0])
        prev = (t, active)
    return times


def build():
    steps, answer, natural, service = [], [], [], []
    for run in RUNS:
        r = load_run(run)
        steps += decode_step_times(run)
        admitted = {e['key']: e['monotonic'] for e in r['worker'] if e['event'] == 'admitted'}
        for e in r['worker']:
            key = e.get('key')
            if key not in r['deadline']:
                continue
            finish = r['records'][key]['monotonic']
            if e['event'] == 'cue_started':
                answer.append(finish - e['monotonic'])
            elif e['event'] == 'thinking_closed' and not e['forced']:
                natural.append(finish - e['monotonic'])
        service += [r['records'][k]['monotonic'] - admitted[k]
                    for k, p in r['policy'].items() if p == 'fixed2048']
    totals = sorted(int(x['model_thinking_tokens']) for x in csv.DictReader(open(STAGE3))
                    if x['configuration'] == 'full')
    med = lambda xs: round(statistics.median(xs), 4)
    est = dict(tau=med(steps), answer=med(answer), service=med(service), totals=totals,
               counts=dict(steps=len(steps), answer=len(answer), service=len(service)),
               natural_close_to_finish=med(natural),
               service_p25=round(statistics.quantiles(service, n=4)[0], 4),
               runs=[str(run.relative_to(ROOT)) for run in RUNS], stage3=str(STAGE3.relative_to(ROOT)))
    OUT.write_text(json.dumps(est, indent=1) + '\n')
    return est


def load_est(tau=1.0, answer=1.0, service=1.0):
    """Estimates as the rule expects them; the multipliers are for the +-25% sensitivity runs."""
    e = json.loads(OUT.read_text())
    totals = e['totals']

    def remaining(t):
        # median extra thinking among stage 3 requests that thought longer than t
        left = [x - t for x in totals if x > t]
        return statistics.median(left) if left else 0
    return dict(tau=e['tau'] * tau, answer=e['answer'] * answer, service=e['service'] * service,
                remaining=remaining)


if __name__ == '__main__':
    est = build()
    print({k: v for k, v in est.items() if k not in ('totals', 'runs')})
