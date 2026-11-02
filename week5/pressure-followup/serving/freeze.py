"""Explicit portable serving source freeze; no deployment or submission."""
import hashlib,json
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
files=[p for p in HERE.iterdir() if p.suffix=='.py' or p.name in ['run.sbatch','spec.json','PROTOCOL.md']]
files += [HERE.parent/'screen/common.py',HERE.parent/'screen/inputs/problems.json',HERE.parent/'screen/inputs/manifest.json']
lock={str(p.relative_to(REPO)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}
(HERE/'source-lock.json').write_text(json.dumps(lock,indent=2)+'\n');print('Portable serving lock:',len(lock),'files; not the queued bundle hash.')
