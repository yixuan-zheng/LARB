"""Premise, fix and no-load verdicts from saved Week 5 runs; CPU only.

The rules were written in PLAN.md before measurement. This script only applies
them: it reads the scored rows of every completed condition under results/ and
prints the tables the verdicts rest on. Nothing here can change an outcome.
"""
import argparse
import json
from pathlib import Path

POLICIES = ['fixed2048', 'fixed4096', 'live', 'live_one']
# Policies allowed to think past the fixed 2,048 allowance when nothing waits.
LONGER = ['fixed4096', 'live']
HERE = Path(__file__).resolve().parent


def load():
    """All graded rows of every completed run, keyed by condition."""
    runs = {}
    for path in sorted(HERE.glob('results/job-*/analysis/summary.json')):
        summary = json.loads(path.read_text())
        condition = summary['condition']
        if condition == 'gate':
            continue
        entry = runs.setdefault(condition, dict(runs=[], rows=[], summary=summary))
        entry['runs'].append(path.parent.parent.name)
        entry['rows'] += json.loads((path.parent / 'graded.json').read_text())
    return runs


def cells(rows):
    """(index, block) -> policy -> row, keeping only cells with every policy."""
    table = {}
    for row in rows:
        table.setdefault((row['index'], row['block']), {})[row['policy']] = row
    return {key: value for key, value in table.items() if len(value) == len(POLICIES)}


def premise(table):
    """Does any policy that may think past 2,048 beat fixed2048 in both blocks?"""
    blocks = sorted({block for _, block in table})
    both = {}
    for policy in LONGER:
        won = [index for index in sorted({index for index, _ in table})
               if all((index, block) in table
                      and table[(index, block)][policy]['correct_on_time']
                      and not table[(index, block)]['fixed2048']['correct_on_time']
                      for block in blocks)]
        eventual = [index for index in sorted({index for index, _ in table})
                    if all((index, block) in table
                           and table[(index, block)][policy]['completed_correct']
                           and not table[(index, block)]['fixed2048']['completed_correct']
                           for block in blocks)]
        both[policy] = dict(on_time=won, eventual=eventual)
    return both


def main():
    runs = load()
    report = {}
    for condition, entry in runs.items():
        table = cells(entry['rows'])
        summaries = {s['policy']: s for s in entry['summary']['summary'] if s['n']}
        line = dict(condition=condition, runs=entry['runs'], answers=len(entry['rows']),
                    questions=len({row['index'] for row in entry['rows']}),
                    policies={p: dict(n=s['n'], on_time=s['correct_on_time'],
                                      eventual=s['completed_correct'],
                                      median_s=round(s['median_client_seconds'] or 0, 1),
                                      slowest_s=round(s['p95_client_seconds'] or 0, 1),
                                      queue_s=round(s['mean_queue_seconds'] or 0, 1),
                                      thinking=s['thinking_tokens'], output=s['output_tokens'],
                                      cuts=s['live_reductions'], binding=s['binding_live_cutoffs'])
                               for p, s in summaries.items()})
        if condition == 'one_at_a_time':
            both = premise(table)
            identical = sum(1 for cell in table.values()
                            if (cell['live']['thinking_tokens'], cell['live']['output_tokens'])
                            == (cell['live_one']['thinking_tokens'],
                                cell['live_one']['output_tokens']))
            line.update(longer_than_2048=both, reductions=sum(1 for row in entry['rows']
                                                              if row['live_reduction']),
                        live_vs_live_one=dict(identical_cells=identical, cells=len(table)),
                        premise_verdict='alive' if any(v['on_time'] or v['eventual']
                                                       for v in both.values())
                        else 'dead on this cohort')
        elif 'fixed2048' in summaries and 'live_one' in summaries:
            # Compare only question-blocks where every policy has a row, so a truncated
            # condition (one policy with an extra block) cannot inflate the delta.
            counts = {p: dict(on_time=0, eventual=0) for p in POLICIES}
            for cell in table.values():
                for policy, row in cell.items():
                    counts[policy]['on_time'] += int(row['correct_on_time'])
                    counts[policy]['eventual'] += int(row['completed_correct'])
            base, one = counts['fixed2048'], counts['live_one']
            medians = {p: sorted(cell[p]['client_completion_seconds'] for cell in table.values())
                       for p in POLICIES}
            middle = len(table) // 2
            median = {p: (v[middle] if len(v) % 2 else (v[middle - 1] + v[middle]) / 2)
                      for p, v in medians.items()}
            line['fix_verdict'] = dict(
                cells=len(table),
                on_time={p: counts[p]['on_time'] for p in POLICIES},
                eventual={p: counts[p]['eventual'] for p in POLICIES},
                on_time_delta=one['on_time'] - base['on_time'],
                eventual_delta=one['eventual'] - base['eventual'],
                median_s={p: round(median[p], 1) for p in POLICIES},
                median_ratio=round(median['live_one'] / median['fixed2048'], 2),
                guard_passes=(one['on_time'] >= base['on_time'] - 1
                              and one['eventual'] >= base['eventual'] - 1))
        report[condition] = line
        print(f"== {condition} | runs={entry['runs']} | answers={line['answers']} "
              f"| questions={line['questions']}")
        print(f"{'policy':>10} {'n':>3} {'on-time':>8} {'eventual':>9} {'median_s':>9} "
              f"{'slowest_s':>10} {'queue_s':>8} {'think':>7} {'out':>7} {'cuts':>5} {'bind':>5}")
        for policy, s in line['policies'].items():
            print(f"{policy:>10} {s['n']:>3} {s['on_time']:>8} {s['eventual']:>9} "
                  f"{s['median_s']:>9} {s['slowest_s']:>10} {s['queue_s']:>8} {s['thinking']:>7} "
                  f"{s['output']:>7} {s['cuts']:>5} {s['binding']:>5}")
        for policy, value in line.get('longer_than_2048', {}).items():
            print(f"  {policy:>10} beats fixed2048 in both blocks: "
                  f"on-time {value['on_time']} eventual {value['eventual']}")
        if 'premise_verdict' in line:
            print(f"  live vs live_one identical cells: {line['live_vs_live_one']}"
                  f" | reductions: {line['reductions']}")
            print(f"  premise verdict: {line['premise_verdict']}")
        if 'fix_verdict' in line:
            print(f"  fix verdict: {line['fix_verdict']}")
        print()
    (HERE / 'verdicts.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    argparse.ArgumentParser().parse_args()
    main()
