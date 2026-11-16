"""Build one flat row per eligible 4K prefix from the Week 6 evidence archive.

Run from the repository root:
    python3 -B week7/scoring/build_sheet.py
"""
import csv
import json
import statistics
import tarfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHIVE = ROOT / 'week6/research-handoff/evidence.tar.gz'
OUT = Path(__file__).resolve().parent / 'prefix-sheet.csv'
PAIRS = 'week6/shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix/graded-pairs.json'
READERS = 'week6/question-prefix-comparison'
BOUNDED = ROOT / 'week7/bounded-prefix'           # local 4-bit qwen3-4b, last 512 prefix tokens
FULL27B = ROOT / 'week7/full-prefix-baseline-v2'  # qwen3.8-27b, full prefix

# scores are net benefit (wc - cw) in percentage points. q/p are the week 6
# readers, whose cost was never measured; b/f also carry measured reader tokens.
# bq/fq are the same b/f reader given only the question (protocol rule 1).
# b_sec/f_sec are measured reader wall seconds per prefix, not on the serving gpu:
# b ran warm on apple metal, f on one a100 at concurrency 8
COLUMNS = ['key', 'question_id', 'seed', 'block', 'outcome',
           'short_correct', 'short_tokens', 'long_correct', 'long_tokens', 'extra_tokens',
           'q_score', 'p_score', 'b_score', 'b_in', 'b_out', 'f_score', 'f_in', 'f_out',
           'bq_score', 'fq_score', 'b_sec', 'f_sec']


def load_json(tar, name):
    return json.load(tar.extractfile(name))


def load_scores(tar, mapping, reader):
    scores = {}
    for line in tar.extractfile(f'{READERS}/{reader}/annotations.jsonl'):
        if line.strip():
            entry = json.loads(line)
            scores[str(mapping[reader][entry['case_id']])] = entry['wc'] - entry['cw']
    return scores


def load_week7_reader(folder, pick, score, cost):
    mapping = json.loads((folder / 'mapping.json').read_text())
    out = {}
    for line in (folder / 'forecasts.jsonl').read_text().splitlines():
        if line.strip():
            entry = json.loads(line)
            key = pick(mapping[entry['case_id']])
            if key:
                out[key] = (score(entry), *cost(entry))
    return out


def top_count(rows, column, count):
    # same tie rule as the frozen evaluation: ties at the cutoff share the remaining slots
    scores = [r[column] for r in rows]
    if count == 0:
        return [0.0] * len(rows)
    cut = sorted(scores, reverse=True)[count - 1]
    higher = sum(s > cut for s in scores)
    tied = sum(s == cut for s in scores)
    return [1.0 if s > cut else (count - higher) / tied if s == cut else 0.0 for s in scores]


def score_policy(rows, column, count):
    weights = top_count(rows, column, count)
    correct = sum(r['short_correct'] + w * (r['long_correct'] - r['short_correct']) for r, w in zip(rows, weights))
    tokens = sum(r['short_tokens'] + w * r['extra_tokens'] for r, w in zip(rows, weights))
    return correct, tokens


def main():
    with tarfile.open(ARCHIVE) as tar:
        pairs = load_json(tar, PAIRS)
        mapping = load_json(tar, f'{READERS}/private-mapping.json')
        scores = {reader: load_scores(tar, mapping, reader) for reader in ['q1', 'q2', 'p1', 'p2']}

    bounded = load_week7_reader(
        BOUNDED,
        pick=lambda m: m['key'] if m['condition'] == 'bounded' else None,
        score=lambda e: 100 * (e['probabilities'][1] - e['probabilities'][2]),
        cost=lambda e: (e['input_tokens'], e['output_tokens'], e['seconds']))
    full = load_week7_reader(
        FULL27B,
        pick=lambda m: m[2] if m[0] == 'week6' and m[1] == 'prefix' else None,
        score=lambda e: e['wc'] - e['cw'],
        cost=lambda e: (e['usage']['prompt_tokens'], e['usage']['completion_tokens'], e['wall_seconds']))
    # same readers on the question alone, keyed by question id
    bounded_q = load_week7_reader(
        BOUNDED,
        pick=lambda m: m['key'] if m['condition'] == 'question' else None,
        score=lambda e: 100 * (e['probabilities'][1] - e['probabilities'][2]),
        cost=lambda e: (e['input_tokens'], e['output_tokens']))
    full_q = load_week7_reader(
        FULL27B,
        pick=lambda m: str(m[2]) if m[0] == 'week6' and m[1] == 'question' else None,
        score=lambda e: e['wc'] - e['cw'],
        cost=lambda e: (e['usage']['prompt_tokens'], e['usage']['completion_tokens']))

    rows = []
    for item in sorted(pairs, key=lambda x: x['key']):
        if not item['eligible']:
            continue  # answered on its own before 4K, so there is nothing to extend
        short, long = item['outcomes']['short'], item['outcomes']['long']
        qid, key = str(item['id']), item['key']
        rows.append(dict(
            key=key, question_id=item['id'], seed=item['seed'], block=item['block'],
            outcome=('c' if short['correct'] else 'w') + ('c' if long['correct'] else 'w'),
            short_correct=int(short['correct']), short_tokens=short['tokens'],
            long_correct=int(long['correct']), long_tokens=long['tokens'],
            extra_tokens=long['tokens'] - short['tokens'],
            # question-only readers saw each question once, so both seeds share its score
            q_score=(scores['q1'][qid] + scores['q2'][qid]) / 2,
            p_score=(scores['p1'][key] + scores['p2'][key]) / 2,
            b_score=bounded[key][0], b_in=bounded[key][1], b_out=bounded[key][2],
            f_score=full[key][0], f_in=full[key][1], f_out=full[key][2],
            bq_score=bounded_q[qid][0], fq_score=full_q[qid][0],
            b_sec=bounded[key][3], f_sec=full[key][3]))

    # check against the published numbers before writing
    assert len(rows) == 57 and len({r['question_id'] for r in rows}) == 30
    assert len(bounded) == 57 and len(full) == 57
    assert len(bounded_q) == 30 and len(full_q) == 30
    assert score_policy(rows, 'q_score', 28) == (24, 413107)
    assert score_policy(rows, 'p_score', 28) == (28, 414396)
    assert score_policy(rows, 'b_score', 28) == (22, 391896)  # bounded-prefix/REPORT.md
    assert score_policy(rows, 'f_score', 28)[0] == 27  # full-prefix-baseline-v2, week 6 cohort
    assert score_policy(rows, 'bq_score', 28) == (25, 401126)  # bounded-prefix/REPORT.md
    assert score_policy(rows, 'fq_score', 28)[0] == 21  # full-prefix-baseline-v2, week 6 cohort
    assert round(statistics.median(r['b_sec'] for r in rows), 2) == 2.97  # bounded-prefix/REPORT.md

    with open(OUT, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)

    counts = {o: sum(r['outcome'] == o for r in rows) for o in ['ww', 'wc', 'cw', 'cc']}
    print(f'wrote {len(rows)} rows to {OUT.relative_to(ROOT)}')
    print('outcomes:', counts)
    print('matches week 6 at 28 extensions: Q 24 correct / 413,107 tokens, P 28 / 414,396')


if __name__ == '__main__':
    main()
