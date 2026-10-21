"""Snapshot a completed matched block without changing the running experiment."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);ap.add_argument('--block',type=int,required=True);args=ap.parse_args()
root=args.root;block=args.block
phases=[p for p in json.loads((root/'progress.json').read_text()) if p['block']==block]
assert len(phases)==4 and {p['policy'] for p in phases}=={'full','arrival','admission','live'}
assert all(p['completed'] and len(p['client'])==12 for p in phases)
out=root/'checkpoints'/f'block{block}'
out.mkdir(parents=True,exist_ok=False);(out/'requests').mkdir()
for name in ['trace.json','spec.json','problems100.json','manifest.json']:
    shutil.copy2(root/name,out/name)
for phase in phases:
    for row in phase['client']:
        source=root/'requests'/f"{row['key']}.json"
        if source.exists(): shutil.copy2(source,out/'requests'/source.name)
(out/'phases.json').write_text(json.dumps(phases,indent=2)+'\n')
worker=[]
for line in (root/'worker.jsonl').read_text().splitlines():
    try: event=json.loads(line)
    except json.JSONDecodeError: continue  # Concurrent tail belongs to later phases.
    if event.get('key','').startswith(f'b{block}-'):worker.append(event)
(out/'worker-events.json').write_text(json.dumps(worker,indent=2)+'\n')
files=[p for p in out.rglob('*') if p.is_file()]
(out/'checkpoint.json').write_text(json.dumps(dict(block=block,matched_block_complete=True,
    overall_comparison_complete=False,purpose='Provisional block readback; final full-run audit still required',
    sha256={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}),indent=2)+'\n')
print(out)
