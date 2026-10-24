"""Check recorded generation in the prepared runtime project; emit no private root paths."""
import argparse
import hashlib
import json
from pathlib import Path

ap=argparse.ArgumentParser();ap.add_argument('--runtime-root',type=Path,required=True);ap.add_argument('--output',type=Path,required=True)
ap.add_argument('--plan',type=Path,required=True);args=ap.parse_args()
seen=set();evidence=[]
for sub in ['results','stage3/results','serving-proof/results','burst-policy/results','week4']:
    root=args.runtime_root/sub
    if not root.exists():continue
    for p in sorted(root.rglob('*')):
        if not p.is_file() or ('requests' not in p.parts and p.name!='requests.jsonl'):continue
        if p.suffix not in ['.json','.jsonl']:continue
        records=[json.loads(l) for l in p.read_text().splitlines()] if p.suffix=='.jsonl' else [json.loads(p.read_text())]
        indices=[r.get('index',r.get('problem_index')) for r in records]
        assert all(isinstance(i,int) for i in indices),'Unclassified raw generation record'
        seen.update(indices);evidence.append(dict(path=str(p.relative_to(args.runtime_root)),indices=indices,sha256=hashlib.sha256(p.read_bytes()).hexdigest()))
plan=json.loads(args.plan.read_text());selected=set(plan['sample']['indices_in_rank_order'])
result=dict(scope='Recorded raw generation within the prepared runtime project; unrecorded/external runs remain unknowable.',
    observed_indices=sorted(seen),selected_disjoint_from_observed_generation=not bool(selected&seen),
    additional_indices_beyond_repository_audit=sorted(seen-set(range(100))),
    record_files=len(evidence),inventory_sha256=hashlib.sha256(json.dumps(evidence,sort_keys=True).encode()).hexdigest())
args.output.write_text(json.dumps(result,indent=2)+'\n')
assert result['selected_disjoint_from_observed_generation'] and not result['additional_indices_beyond_repository_audit'],'Additional exposure requires reconciling the frozen plan before generation'
print('PASS: runtime-project generation audit matches the known development range; selected cohort remains disjoint.')
