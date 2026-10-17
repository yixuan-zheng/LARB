"""Check engineering outcomes separately from mathematical answer correctness."""
import json
from pathlib import Path
import statistics
import sys

run = Path(sys.argv[1])
manifest = json.loads((run/'manifest.json').read_text())
rows = [json.loads(line) for line in (run/'requests.jsonl').read_text().splitlines()]
indices = manifest.get('indices', list(range(10)))
assert [r['index'] for r in rows] == indices[:len(rows)]
if manifest['completed']:
    assert len(rows) == len(indices)
for r in rows:
    ids = r['token_ids']
    assert len(ids) == r['generated_tokens']
    boundary = r['thinking_tokens']
    if boundary is not None:
        assert ids[boundary] == 151668
        assert boundary+1+r['answer_tokens'] == len(ids)
        transition_ids = manifest.get('transition_ids', [151668])
        assert boundary <= r['thinking_budget'] + transition_ids.index(151668)
    assert r['answer_tokens'] <= manifest['answer_cap']
    if r['forced_positions']:
        transition_ids = manifest.get('transition_ids', [151668])
        assert r['forced_positions'] == list(range(r['thinking_budget'], r['thinking_budget']+len(transition_ids)))
        assert ids[r['thinking_budget']:r['thinking_budget']+len(transition_ids)] == transition_ids
        assert boundary == r['thinking_budget']+transition_ids.index(151668)
    assert r['elapsed_seconds'] > 0
    for t in r['events'].values():
        assert 0 <= t <= r['elapsed_seconds']
print('Completed:',manifest['completed'],'Requests:',len(rows))
print('| Index | Pre-close tokens | Answer tokens | Forced | Prefix match | Boxed answer | Finish | Seconds |')
print('| --- | --- | --- | --- | --- | --- | --- | --- |')
for r in rows:
    print(f"| {r['index']} | {r['thinking_tokens']} | {r['answer_tokens']} | {bool(r['forced_positions'])} | {r['prefix_matches_stage1']} | {r['extracted_answer']} | {r['finish_reason']} | {r['elapsed_seconds']:.2f} |")
print('Forced transitions:',sum(bool(r['forced_positions']) for r in rows))
print('Nonempty continuations:',sum(bool(r['final_answer'].strip()) for r in rows))
print('Boxed answers:',sum(r['extracted_answer'] is not None for r in rows))
print('Normal EOS completions:',sum(r['finish_reason']=='eos' for r in rows))
print('Reopened thinking:',sum(r['thinking_reopened'] for r in rows))
print('Matching baseline prefixes:',sum(r['prefix_matches_stage1'] for r in rows))
print('Raw exact matches:',sum(r['exact_match'] for r in rows))
print('Median total seconds:',statistics.median(r['elapsed_seconds'] for r in rows))
print('Total seconds:',sum(r['elapsed_seconds'] for r in rows))
latencies=[r['events']['close_seconds']-r['events']['trigger_seconds'] for r in rows if 'trigger_seconds' in r['events'] and 'close_seconds' in r['events']]
if latencies:
    print('Median forced-marker observation delay ms:',1000*statistics.median(latencies))
print('\nReview answers:')
for r in rows:
    print(r['index'],'predicted=',repr(r['extracted_answer']),'reference=',repr(r['reference']))
