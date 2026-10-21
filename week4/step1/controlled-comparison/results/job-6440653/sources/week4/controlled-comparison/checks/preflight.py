"""Exact comparison source inventory verification without GPU imports."""
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import sys

here=Path(__file__).resolve().parents[1]
repo=here.parents[1]
legacy=Path(os.environ.get('LARB_WEEK3_ROOT',repo/'week3/larb')).resolve()
lock=json.loads((here/'source-lock.json').read_text())
for name,sha in lock.items():
    path=legacy/name.removeprefix('week3/larb/') if name.startswith('week3/larb/') else repo/name
    assert hashlib.sha256(path.read_bytes()).hexdigest()==sha,name
    if path.suffix=='.py': compile(path.read_text(),str(path),'exec')
assert importlib.metadata.version('vllm')=='0.11.2'
if '--require-gate' in sys.argv:
    gate=json.loads((here/'gate.json').read_text())
    assert gate['passed'], 'Real concurrent 1C validation is required'
    assert all(lock[name]==sha for name,sha in gate['candidate_sources'].items())
    assert hashlib.sha256((legacy/'stage3/problems100.json').read_bytes()).hexdigest()==gate['dataset_sha256']
    assert hashlib.sha256((legacy/'stage3/protocol.json').read_bytes()).hexdigest()==gate['protocol_sha256']
print(json.dumps(dict(passed=True,sources=len(lock),vllm='0.11.2'),indent=2))
