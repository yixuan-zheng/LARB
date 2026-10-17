"""Validate saved baseline records and print a compact table for manual review."""
import json
from pathlib import Path
import statistics
import sys

run = Path(sys.argv[1])
manifest = json.loads((run/'manifest.json').read_text())
rows = [json.loads(line) for line in (run/'requests.jsonl').read_text().splitlines()]
assert [r['index'] for r in rows] == list(range(len(rows)))
for r in rows:
    assert len(r['token_ids']) == r['generated_tokens']
    if r['thinking_closed']:
        assert r['thinking_tokens'] + 1 + r['answer_tokens'] == r['generated_tokens']
    assert r['elapsed_seconds'] > 0
if manifest['completed']:
    assert len(rows) == 10
print('Completed:', manifest['completed'], 'Requests:', len(rows))
print('| Index | Thinking tokens | Output tokens | Seconds | Exact match | Finish |')
print('| --- | --- | --- | --- | --- | --- |')
for r in rows:
    print(f"| {r['index']} | {r['thinking_tokens']} | {r['generated_tokens']} | {r['elapsed_seconds']:.2f} | {r['exact_match']} | {r['finish_reason']} |")
print('Median seconds:', statistics.median(r['elapsed_seconds'] for r in rows))
print('Range seconds:', min(r['elapsed_seconds'] for r in rows), max(r['elapsed_seconds'] for r in rows))
print('Total generation seconds:', sum(r['elapsed_seconds'] for r in rows))
print('Exact matches:', sum(r['exact_match'] for r in rows))
closed = [r for r in rows if r['thinking_closed']]
if closed:
    print('Thinking share, closed outputs only:', sum(r['thinking_tokens'] for r in closed)/sum(r['generated_tokens'] for r in closed))
print('Unclosed output tokens:', sum(r['generated_tokens'] for r in rows if not r['thinking_closed']))
print('\nAnswers to review:')
for r in rows:
    print(r['index'], 'predicted=', repr(r['extracted_answer']), 'reference=', repr(r['reference']))
