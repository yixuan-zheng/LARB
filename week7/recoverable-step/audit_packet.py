"""Select a fixed, outcome-blind sample of reader decisions for review."""
import hashlib
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
path = root / 'step.jsonl'
assert hashlib.sha256(path.read_bytes()).hexdigest() == path.with_suffix('.sha256').read_text().strip()
predictions = [json.loads(line) for line in path.read_text().splitlines()]
packets = {row['case_id']: row for row in json.loads((root / 'step-packets.json').read_text())}
assert len(packets) == len(predictions) and set(packets) == {row['case_id'] for row in predictions}
ordered = sorted(predictions, key=lambda row: hashlib.sha256(f"larb-step-audit:{row['case_id']}".encode()).digest())
sample = []
for decision, limit in [('STEP', 10), ('READY', 5)]:
    for row in [item for item in ordered if item['decision'] == decision][:limit]:
        sample.append({**packets[row['case_id']], 'decision': decision, 'response': row['response']})
with (root / 'audit-packet.json').open('x') as out:
    json.dump(sample, out, indent=2, ensure_ascii=False)
    out.write('\n')
