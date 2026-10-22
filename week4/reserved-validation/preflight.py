"""Verify source/input/plan locks on CPU before spending a GPU allocation."""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
from execution import digest,source_path

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
ap=argparse.ArgumentParser();ap.add_argument('--local',action='store_true');args=ap.parse_args()
legacy=Path(os.environ.get('LARB_WEEK3_ROOT',REPO/'week3/larb'))
lock=json.loads((HERE/'source-lock.json').read_text())
for name,expected in lock.items():
    path=source_path(REPO,legacy,name)
    assert digest(path)==expected,'Source mismatch: '+name
    if path.suffix=='.py':compile(path.read_text(),name,'exec')
plan=json.loads((REPO/'week4/evaluation-plan/plan.json').read_text())
candidate=json.loads((REPO/'week4/evaluation-plan/candidate-lock.json').read_text())
assert all(lock[n]==h for n,h in candidate['files'].items())
inputs=json.loads((HERE/'inputs/dataset-manifest.json').read_text())
assert digest(HERE/'inputs/problems100.json')==inputs['sparse_input_sha256']
problems=json.loads((HERE/'inputs/problems100.json').read_text());assert len(problems)==500
assert {i for i,r in enumerate(problems) if r is not None}==set(plan['sample']['indices_in_rank_order']+[0,2])
for row in inputs['selected_rows']:
    import hashlib
    data=json.dumps(problems[row['index']],sort_keys=True,separators=(',',':')).encode()
    assert hashlib.sha256(data).hexdigest()==row['row_sha256']
if not args.local:
    for name in ['vllm','torch','transformers']:assert metadata.version(name).split('+')[0]==plan['engine'][name],name
print('PASS: exact source inventory, unchanged candidate, frozen plan, sparse input, and runtime pins checked'+(' (local runtime check skipped)' if args.local else ''))
