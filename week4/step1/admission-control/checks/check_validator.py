"""After a real passing smoke, prove key evidence corruptions are rejected.

Only scratch copies are changed. The recorded run remains untouched.
"""
import argparse
import json
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validate_smoke import validate


def write_copy(root, name, value, jsonl=False):
    path = root/name
    path.unlink()  # Break the scratch symlink before writing.
    path.write_text(('\n'.join(json.dumps(row) for row in value) if jsonl
                     else json.dumps(value, indent=2))+'\n')


def load(root, name, jsonl=False):
    text = (root/name).read_text()
    return [json.loads(line) for line in text.splitlines()] if jsonl else json.loads(text)


def corrupt(root, case):
    if case in ('worker_started_early','admission_revision','cap_failure','no_live_updates'):
        rows = load(root,'worker.jsonl',True)
        if case=='worker_started_early':
            next(r for r in rows if r['event']=='admitted')['tokens']=1
        elif case=='admission_revision':
            row = dict(next(r for r in rows if r['event']=='live_reduction'))
            row['key']=row['key'].replace('live-','admission-',1)
            rows.append(row)
        elif case=='cap_failure':
            rows.append(dict(event='answer_cap',key='live-00',tokens=99,monotonic=0))
        else:
            rows=[r for r in rows if r['event']!='live_reduction']
        write_copy(root,'worker.jsonl',rows,True)
    elif case=='wrong_admission_budget':
        rows=load(root,'scheduler.jsonl',True)
        row=next(r for r in rows if r['event']=='admission_decision' and r['policy']=='admission')
        row['budget']=1
        write_copy(root,'scheduler.jsonl',rows,True)
    elif case=='changed_trace':
        trace=load(root,'trace.json')
        trace['arrivals'][0]['offset_seconds']+=1
        write_copy(root,'trace.json',trace)
    elif case=='source_hash_mismatch':
        manifest=load(root,'manifest.json')
        first=next(iter(manifest['sources']))
        manifest['sources'][first]='bad'
        write_copy(root,'manifest.json',manifest)
    elif case=='incomplete_run':
        complete=load(root,'run-complete.json')
        complete['complete']=False
        write_copy(root,'run-complete.json',complete)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    args=parser.parse_args()
    original=args.root.resolve()
    baseline=validate(original)
    if not baseline['passed']:
        raise RuntimeError('A passing real baseline is required for corruption checks')
    results=[]
    for case in ['worker_started_early','admission_revision','cap_failure','no_live_updates',
                 'wrong_admission_budget','changed_trace','source_hash_mismatch','incomplete_run']:
        with tempfile.TemporaryDirectory(prefix='validator-') as directory:
            scratch=Path(directory)
            for source in original.iterdir():
                (scratch/source.name).symlink_to(source,target_is_directory=source.is_dir())
            corrupt(scratch,case)
            result=validate(scratch)
            results.append(dict(case=case,rejected=not result['passed'],
                                failed_checks=[r['name'] for r in result['checks'] if not r['passed']]))
    print(json.dumps(dict(passed=all(r['rejected'] for r in results),cases=results),indent=2))
    raise SystemExit(0 if all(r['rejected'] for r in results) else 1)
