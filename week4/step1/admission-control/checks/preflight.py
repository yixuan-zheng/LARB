"""Check staging on the login node before consuming a GPU allocation."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sys

here = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(here))
import bootstrap

lock = json.loads((here/'source-lock.json').read_text())
actual_names = {str(p.relative_to(bootstrap.REPO)) for p in here.glob('*.py')
                if not p.name.startswith('.')}
expected_names = {name for name in lock if name.startswith('week4/') and name.endswith('.py')}
assert actual_names==expected_names, (actual_names-expected_names,expected_names-actual_names)
checked = {}
for name, expected in lock.items():
    path = (bootstrap.LEGACY/name.removeprefix('week3/larb/')
            if name.startswith('week3/larb/') else bootstrap.REPO/name)
    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    if actual != expected:
        raise RuntimeError('Source mismatch: '+name)
    checked[name] = actual
    if path.suffix=='.py':
        compile(path.read_text(),str(path),'exec')
versions = {name:importlib.metadata.version(name)
            for name in ['vllm','torch','transformers','aiohttp','fastapi']}
assert versions['vllm']=='0.11.2',versions
print(json.dumps(dict(passed=True,versions=versions,sources=checked),indent=2))
