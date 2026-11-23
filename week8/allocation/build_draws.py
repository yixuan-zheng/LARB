"""Build one flat row per Experiment 2 draw, the workload for the allocation replay.

Run from the repository root:
    python3 -B week8/allocation/build_draws.py

Each of the 58 eligible 4K checkpoints has eight short draws (answer at 4,096
thinking tokens) and eight long draws (continue up to 8,192). The replay looks up
a draw's suffix length and grade instead of generating anything.
"""
import csv
import json
import statistics
import tarfile
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / 'week7/continuation-sampling'
EVIDENCE = STUDY / 'results/evidence.tar.gz'
RELEASE = STUDY / 'full-release.tar.gz'
SUMMARY = STUDY / 'results/full-summary.json'
COHORT = ROOT / 'week7/scaled-serving/artifacts/cohort.json'
OUT = Path(__file__).resolve().parent / 'draws.csv'
CALLS = 'week7/continuation-sampling/results/run/calls/'

# suffix_tokens is everything generated after the 4K checkpoint: the rest of the
# thinking, the cue if forced, and the answer. wall_seconds was measured on one
# L40S at concurrency 1, so the replay uses tokens, not these seconds
COLUMNS = ['call_id', 'question_id', 'prefix', 'arm', 'replicate', 'correct', 'reason',
           'input_tokens', 'suffix_tokens', 'forced', 'wall_seconds']


def load_calls():
    calls = {}
    with tarfile.open(EVIDENCE) as tar:
        for member in tar:
            if member.name.startswith(CALLS) and member.name.endswith('.json'):
                record = json.load(tar.extractfile(member))
                calls[record['task']['call_id']] = record
    return calls


def load_prefixes():
    with tarfile.open(RELEASE) as tar:
        return json.load(tar.extractfile('./prefixes.json'))


def main():
    calls = load_calls()
    prefixes = load_prefixes()
    summary = json.loads(SUMMARY.read_text())
    grades = {g['call_id']: g for g in summary['grades']}
    assert prefixes['dataset']['repository'] == 'MathArena/aime_2026'

    rows = []
    for call_id in sorted(calls):
        record, task = calls[call_id], calls[call_id]['task']
        pair = prefixes['prefixes'][task['prefix_key']]
        assert record['input_tokens'] == len(pair['prompt_token_ids']) + len(pair['prefix_token_ids'])
        rows.append(dict(
            call_id=call_id,
            # same id format as the scaled-serving cohort, so traces can name these questions
            question_id=f"aime2026-{int(pair['id']):03d}",
            prefix=task['prefix_key'], arm=task['arm'], replicate=task['replicate'],
            correct=grades[call_id]['correct'], reason=grades[call_id]['reason'],
            input_tokens=record['input_tokens'], suffix_tokens=len(record['suffix_token_ids']),
            forced=int(record['forced']), wall_seconds=round(record['elapsed_seconds'], 3)))

    # check against the published numbers before writing
    short = [r for r in rows if r['arm'] == 'short']
    long = [r for r in rows if r['arm'] == 'long']
    assert len(rows) == 928 and len(short) == len(long) == 464
    assert len({r['prefix'] for r in rows}) == 58 and len({r['question_id'] for r in rows}) == 29
    assert sum(r['correct'] for r in short) == 167 and sum(r['correct'] for r in long) == 230
    assert sum(r['suffix_tokens'] for r in rows) == 2_994_681  # continuation-sampling/REPORT.md
    assert sum(r['reason'] == 'answer_cap' for r in rows) == 170
    assert round(statistics.mean(r['wall_seconds'] for r in short), 2) == 22.22
    assert round(statistics.mean(r['wall_seconds'] for r in long), 2) == 77.19

    # per-prefix p8 - p4 must match the published value table
    by_prefix = defaultdict(lambda: defaultdict(list))
    for r in rows:
        by_prefix[r['prefix']][r['arm']].append(r['correct'])
    for key, arms in by_prefix.items():
        assert len(arms['short']) == len(arms['long']) == 8
        delta = statistics.mean(arms['long']) - statistics.mean(arms['short'])
        assert abs(delta - summary['prefixes'][key]['delta']) < 1e-12, key

    cohort = json.loads(COHORT.read_text())
    known = set(cohort['main_ids']) | set(cohort['preview_ids'])
    in_pool = {r['question_id'] for r in rows} & known

    with open(OUT, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    print(f'wrote {len(rows)} rows to {OUT.relative_to(ROOT)}')
    print('matches experiment 2: 167/464 short, 230/464 long, 2,994,681 suffix tokens, 170 answer caps')
    print(f'mean suffix tokens: short {statistics.mean(r["suffix_tokens"] for r in short):.0f}, '
          f'long {statistics.mean(r["suffix_tokens"] for r in long):.0f}')
    print(f'{len(in_pool)} of 29 questions are in the scaled-serving main or preview pool')


if __name__ == '__main__':
    main()
