"""Compact read-only progress snapshot, safe to run on the login node."""
import json
from pathlib import Path
from collections import Counter
root=Path('stage3/results')
counts=Counter(); complete=0; states=[]
for task in sorted(root.glob('task-*')):
    try:
        manifest=json.loads((task/'manifest.json').read_text())
    except (FileNotFoundError,json.JSONDecodeError):
        continue
    n=len(list((task/'requests').glob('*.json')))
    name=manifest['configuration']['name']
    counts[name]+=n
    complete+=manifest['completed']
    states.append((manifest['task'],name,n,manifest['completed']))
print(json.dumps(dict(requests=sum(counts.values()),by_configuration=dict(counts),completed_tasks=complete,started_tasks=len(states))))
