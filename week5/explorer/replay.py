"""C2: replay saved Week 4 runs through the shadow rule -> shadow/<run>.jsonl.gz.

At every scheduler step where both slots hold measured requests of one phase and
at least one request waits, rebuild what the controller could see (tokens,
budget, closed/cued, waiting queue, deadlines) and log what the shadow rule and
cut-whenever-full would do. Nothing is acted on; the records are only read.

usage: python3 replay.py [run_dir ...]   (default: all Week 4 runs in records.RUNS)
"""
import bisect
import gzip
import json
import sys
from collections import Counter
from pathlib import Path

from estimates import load_est
from records import RUNS, iter_steps, load_run
from targeting import category, cut_all_decision, eligible, free_time, shadow_decision

OUT = Path(__file__).with_name('shadow')
EVERY = 1.0  # re-evaluate an unchanged state at most once per second


class Timeline:
    """Budget changes, cue start and natural close per request, from the worker events."""
    def __init__(self, worker):
        self.budgets, self.cue, self.close = {}, {}, {}
        for e in worker:
            if e['event'] == 'admitted':
                self.budgets[e['key']] = [(e['monotonic'], e['initial_budget'])]
            elif e['event'] == 'live_reduction':
                self.budgets[e['key']].append((e['monotonic'], e['budget']))
            elif e['event'] == 'cue_started':
                self.cue[e['key']] = e['monotonic']
            elif e['event'] == 'thinking_closed':
                self.close.setdefault(e['key'], e['monotonic'])

    def state(self, key, t, tokens):
        changes = self.budgets.get(key, [(t, None)])
        i = bisect.bisect_right([c[0] for c in changes], t) - 1
        return dict(key=key, tokens=tokens, budget=changes[max(i, 0)][1],
                    closed=self.close.get(key, float('inf')) <= t,
                    cued=self.cue.get(key, float('inf')) <= t)


def replay(run, est):
    r = load_run(run)
    timeline = Timeline(r['worker'])
    prompt = {k: len(rec['prompt_token_ids']) for k, rec in r['records'].items()}
    rows, episode, last = [], 0, None
    live_two = {}  # first time the week 4 live rule (two waiters) would cut each request
    for t, active, waiting in iter_steps(run):
        keys = [k for k in active if k in r['deadline']]
        phase = keys[0].rsplit('-', 1)[0] if keys else None
        queue = [k for k in waiting if k.startswith(f'{phase}-') and k in r['deadline']]
        if len(keys) < 2 or not queue:
            last = None
            continue
        # computed tokens include the prompt; generated = computed - prompt + 1
        running = [timeline.state(k, t, max(0, active[k] - prompt[k] + 1)) for k in keys]
        waiters = [dict(key=k, deadline=r['deadline'][k]) for k in queue]
        if r['policy'][keys[0]] == 'live':
            for k in cut_all_decision(running, waiters, threshold=2):
                live_two.setdefault(k, t)
        sig = (tuple(keys), tuple(queue), tuple((x['budget'], x['closed'], x['cued'], eligible(x)) for x in running))
        if last is None:
            episode += 1
        elif sig == last[1] and t - last[0] < EVERY:
            continue
        last = (t, sig)
        shadow = shadow_decision(t, running, waiters, est)
        baseline = cut_all_decision(running, waiters)
        rows.append(dict(
            run=r['name'], condition=r['condition'], policy=r['policy'][keys[0]], phase=phase,
            episode=episode, t=round(t, 3),
            running=[dict(x, slot_s=round(free_time(x, est), 1)) for x in running],
            waiters=[dict(key=w['key'], slack_s=round(w['deadline'] - t, 1)) for w in waiters],
            shadow=shadow, baseline=baseline, category=category(shadow, baseline)))
    return r, rows, checks(r, timeline, live_two)


def checks(r, timeline, live_two):
    # deadlines: server-clock finish vs deadline must agree with the graded client-side on-time
    flips = [k for k in r['deadline']
             if (r['records'][k]['monotonic'] <= r['deadline'][k])
             != (r['graded'][k]['client_completion_seconds'] <= r['D'])]
    # state rebuild: our two-waiter rule should fire when the recorded live rule did
    recorded = {k: v[1][0] for k, v in timeline.budgets.items() if len(v) > 1}
    matched = [k for k in recorded if k in live_two and abs(live_two[k] - recorded[k]) < 0.5]
    return dict(requests=len(r['deadline']), deadline_flips=flips, live_cuts_recorded=len(recorded),
                live_cuts_predicted=len(live_two), live_cuts_matched=len(matched),
                unmatched=sorted((set(recorded) | set(live_two)) - set(matched)))


def main(runs):
    est = load_est()
    OUT.mkdir(exist_ok=True)
    for run in runs:
        r, rows, check = replay(Path(run), est)
        with gzip.open(OUT / f"{r['name']}.jsonl.gz", 'wt') as f:
            for row in rows:
                f.write(json.dumps(row) + '\n')
        (OUT / f"{r['name']}.checks.json").write_text(json.dumps(check, indent=1) + '\n')
        print(r['name'], r['condition'], f"{len(rows)} decision points,", f"{rows[-1]['episode'] if rows else 0} episodes")
        print('  categories', dict(Counter(row['category'] for row in rows)))
        print('  checks', check)


if __name__ == '__main__':
    main(sys.argv[1:] or RUNS)
