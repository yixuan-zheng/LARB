"""C3: does the shadow rule ever choose differently from cut-whenever-full?

Replays every Week 4 run (base estimates and +-25% on tau/answer/service) and writes
results/:
  discrimination.csv  decision points and full-server episodes per condition/policy, by category
  states.csv          what the states look like in each category
  plausibility.csv    rule's no-cut prediction vs what actually happened, in phases that never cut live
  sensitivity.csv     share of cuttable decision points where the rule disagrees, per setting

This is a decision test on recorded trajectories, not a result: after a real or
hypothetical cut the trajectory would diverge, so each point is judged on its own state.
"""
import csv
import statistics
from collections import Counter, defaultdict
from pathlib import Path

import replay
from estimates import load_est
from records import RUNS

OUT = Path(__file__).with_name('results')
CATEGORIES = ['agree', 'doomed', 'fine', 'one_of_two', 'other']
SETTINGS = {'base': {}}
for name in ('tau', 'answer', 'service'):
    SETTINGS[f'{name}-25'] = {name: 0.75}
    SETTINGS[f'{name}+25'] = {name: 1.25}
NO_LIVE_CUTS = ('fixed4096', 'admission')  # the record is the no-cut branch here


def run_all(est):
    rows, runs = [], {}
    for run in RUNS:
        r, out, _ = replay.replay(run, est)
        rows += out
        runs[r['name']] = r
    return rows, runs


def episodes(rows):
    """Per full-server episode where cut-whenever-full cuts at some point: when does the rule cut?"""
    first = defaultdict(dict)
    for row in rows:
        ep = first[(row['run'], row['phase'], row['episode'])]
        ep.setdefault('condition', row['condition'])
        ep.setdefault('policy', row['policy'])
        if row['baseline']:
            ep.setdefault('baseline', row['t'])
        if row['shadow']['cut']:
            ep.setdefault('shadow', row['t'])
    out = []
    for ep in first.values():
        if 'baseline' not in ep:
            continue
        if 'shadow' not in ep:
            kind = 'never'
        else:
            kind = 'same_time' if ep['shadow'] <= ep['baseline'] else 'later'
        out.append(dict(ep, kind=kind))
    return out


def discrimination(rows):
    table = []
    groups = defaultdict(list)
    for row in rows:
        groups[(row['condition'], row['policy'])].append(row)
    eps = defaultdict(list)
    for ep in episodes(rows):
        eps[(ep['condition'], ep['policy'])].append(ep['kind'])
    for (condition, policy), group in sorted(groups.items()):
        cuttable = [row for row in group if row['baseline']]
        counts = Counter(row['category'] for row in cuttable)
        kinds = Counter(eps[(condition, policy)])
        table.append(dict(condition=condition, policy=policy, points=len(group), cuttable=len(cuttable),
                          **{c: counts[c] for c in CATEGORIES},
                          disagree_share=round(1 - counts['agree'] / len(cuttable), 3) if cuttable else '',
                          episodes_cuttable=sum(kinds.values()), episodes_never=kinds['never'],
                          episodes_later=kinds['later'], episodes_same_time=kinds['same_time']))
    return table


def states(rows):
    """Median state features per category, over decision points where something was cuttable."""
    groups = defaultdict(list)
    for row in rows:
        if row['baseline']:
            groups[row['category']].append(row)
    med = lambda xs: round(statistics.median(xs), 1) if xs else ''
    out = []
    for cat in CATEGORIES:
        group = groups.get(cat, [])
        out.append(dict(category=cat, points=len(group),
                        waiters=med([len(r['waiters']) for r in group]),
                        head_slack_s=med([r['waiters'][0]['slack_s'] for r in group]),
                        max_running_tokens=med([max(x['tokens'] for x in r['running']) for r in group]),
                        cuttable_running=med([len(r['baseline']) for r in group]),
                        share_running_past_2048=round(statistics.mean(
                            [any(x['tokens'] > 2048 for x in r['running']) for r in group]), 3) if group else ''))
    return out


def plausibility(rows, runs):
    """Predicted no-cut outcome for the first two waiters vs the recorded one (timing only)."""
    points, first = Counter(), {}
    for row in rows:
        if row['policy'] not in NO_LIVE_CUTS:
            continue
        r = runs[row['run']]
        for w, predicted in zip(row['waiters'], row['shadow']['base']):
            actual = r['records'][w['key']]['monotonic'] <= r['deadline'][w['key']]
            points[(predicted, actual)] += 1
            first.setdefault(w['key'], (predicted, actual))
    waiters = Counter(first.values())
    label = {True: 'made', False: 'missed'}
    return [dict(unit=unit, predicted=label[p], actual=label[a], n=counts[(p, a)])
            for unit, counts in (('decision_point', points), ('waiter_first_call', waiters))
            for p in (True, False) for a in (True, False)]


def write(name, table):
    OUT.mkdir(exist_ok=True)
    with open(OUT / name, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)


def main():
    replay.main(RUNS)
    sensitivity = []
    for name, scale in SETTINGS.items():
        rows, runs = run_all(load_est(**scale))
        cuttable = [row for row in rows if row['baseline']]
        counts = Counter(row['category'] for row in cuttable)
        kinds = Counter(ep['kind'] for ep in episodes(rows))
        sensitivity.append(dict(setting=name, cuttable=len(cuttable),
                                disagree_share=round(1 - counts['agree'] / len(cuttable), 3),
                                **{c: counts[c] for c in CATEGORIES},
                                episodes_cuttable=sum(kinds.values()), episodes_never=kinds['never'],
                                episodes_later=kinds['later']))
        if name == 'base':
            write('discrimination.csv', discrimination(rows))
            write('states.csv', states(rows))
            write('plausibility.csv', plausibility(rows, runs))
    write('sensitivity.csv', sensitivity)
    for f in ('discrimination.csv', 'states.csv', 'plausibility.csv', 'sensitivity.csv'):
        print(f'\n== {f}')
        print((OUT / f).read_text())


if __name__ == '__main__':
    main()
