"""Reproduce the repository exposure audit and frozen 5A planning artifacts; no inference."""
import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def dump(name, data):
    (HERE/name).write_text(json.dumps(data, indent=2, sort_keys=True)+'\n')

def build():
    tracked = subprocess.check_output(['git','ls-files','week1','week2','week3','week4','preflight'], cwd=REPO, text=True).splitlines()
    groups = defaultdict(list)
    generated = set()
    unexpected = []
    for name in tracked:
        if not name.startswith(('week3/larb/', 'week4/step1/')):
            continue
        if '/requests/' not in name and not name.endswith('/requests.jsonl'):
            continue
        path = REPO/name
        records = [json.loads(s) for s in path.read_text().splitlines()] if path.suffix == '.jsonl' else [json.loads(path.read_text())]
        for r in records:
            i = r.get('index', r.get('problem_index'))
            if not isinstance(i, int):
                unexpected.append(name)
                continue
            generated.add(i)
            groups[name.split('/requests')[0]].append((name, i, sha(path)))
    assert generated == set(range(100)), sorted(generated)
    assert not unexpected, unexpected
    other_mentions=[]
    for name in tracked:
        if name.startswith(('week3/larb/','week4/')) or not name.endswith(('.py','.json','.jsonl','.md','.yml','.yaml')):
            continue
        try: text=(REPO/name).read_text().lower()
        except UnicodeError: continue
        if any(s in text for s in ['math-500','math500','math_500']):
            other_mentions.append(name)
    assert not other_mentions, 'Review additional MATH-500 uses before selecting a reserve: '+str(other_mentions)
    evidence=[]
    for name, rows in sorted(groups.items()):
        unique_files=sorted({(p,h) for p,_,h in rows})
        evidence.append(dict(root=name, records=len(rows), indices=sorted({i for _,i,_ in rows}),
                             files=len(unique_files), inventory_sha256=hashlib.sha256(json.dumps(unique_files,separators=(',',':')).encode()).hexdigest()))
    protocol='week3/larb/stage3/protocol.json'
    dump('exposure.json',dict(scope='Tracked repository artifacts only; external/uncommitted runs and pretraining contamination cannot be ruled out.',
        dataset='HuggingFaceH4/MATH-500', revision='6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be',
        indexing='Zero-based line order in test.jsonl at the pinned revision',
        protocol=dict(path=protocol,sha256=sha(REPO/protocol)), generated_indices=sorted(generated),
        provisionally_eligible_indices=list(range(100,500)), other_week_math500_mentions=other_mentions,
        evidence=evidence, omitted_setup_attempts='Two documented zero-request failures do not expand exposure.',
        runtime_requirement='Reconcile external exposure before generation; fetch only pinned data, validate first-100 prefix and unique IDs, and write input hashes before measuring. No automatic substitution.'))
    ranked=sorted(range(100,500),key=lambda i:hashlib.sha256(f'week4-5A-v1:{i}'.encode()).hexdigest())
    sample=ranked[:24]
    current=json.loads((HERE/'plan.json').read_text())
    assert current['sample']['indices_in_rank_order']==sample
    for shard in current['sample']['shards']:
        ids=shard['indices']
        assert len(ids)==12 and all(i in sample for i in ids)
        assert shard['block_positions']==[ids,ids[6:]+ids[:6]]
    assert set(sample).isdisjoint(generated)
    source_paths=['week4/step1/admission-control/'+n for n in ['bootstrap.py','w4_policy.py','w4_adapter.py','w4_server.py']]
    source_paths += ['week3/larb/burst-policy/adapter.py','week3/larb/burst-policy/policy.py','week3/larb/serving-proof/control.py',
                     'week3/larb/code/baseline.py','week3/larb/code/grade_stage3.py']
    candidate=json.loads((HERE/'candidate-lock.json').read_text())
    assert candidate['files']=={p:sha(REPO/p) for p in source_paths}, 'Candidate changed: create a new plan rather than silently refreshing this lock.'
    root=REPO/'week4/step1/controlled-comparison/results/job-6440653'
    service=[json.loads(s) for s in (root/'service.jsonl').read_text().splitlines()]
    worker=[json.loads(s) for s in (root/'worker.jsonl').read_text().splitlines()]
    complete={r['key']:r for r in service if r['event']=='completed'}
    closed={r['key']:r for r in worker if r['event']=='thinking_closed'}
    cue=[r for r in worker if r['event']=='cue_started' and r['key'] in ['b0-live-01','b1-live-01']]
    cases=json.loads((root/'analysis/cases.json').read_text())
    dump('signal-audit.json',dict(source_root=str(root.relative_to(REPO)),
        files={n:sha(root/n) for n in ['worker.jsonl','service.jsonl','analysis/cases.json']},
        observations=[dict(key=r['key'],cue_to_server_final_seconds=complete[r['key']]['monotonic']-r['monotonic'],
                           close_detection_to_server_final_seconds=complete[r['key']]['monotonic']-closed[r['key']]['monotonic']) for r in cue],
        rescued_unique_problem_indices=sorted({r['index'] for b in cases['blocks'] for r in b['deadline_changes'] if r['deadline_delta']>0}),
        available=['queue membership and admission','generated progress','budget/cue/close events','same-host final completion','offline client deadlines'],
        missing=['online deadline metadata in the current controller','online remaining-natural-work predictor','online answer reserve estimate','intervention-specific counterfactual','calibrated quality risk'],
        interpretation='Two binding pivots are a feasibility clue, not a predictor training set or counterfactual replay evaluation.'))
    # Materialize illustrative traces with prior development calibration, never held-out timing.
    frozen=json.loads((root/'run-complete.json').read_text())['phases'][0]['client']
    durations=[r['client_finished']-r['scheduled'] for r in frozen]
    minimum=min(durations);unit=max(30.,max(durations));deadline=2*unit
    illustrative=[]
    for condition in current['conditions']:
        offsets=([i*2*unit for i in range(12)] if condition=='low_load' else
                 [0.,0.]+[.25*minimum+.05*i for i in range(10)] if condition=='late_burst' else
                 [.3*unit*i for i in range(12)])
        assert offsets==sorted(offsets) and len(offsets)==12
        illustrative.append(dict(condition=condition,offset_seconds=offsets,relative_deadline_seconds=deadline,
                                 horizon_seconds=max(offsets)+deadline))
    dump('trace-examples.json',dict(status='Illustrative only; numeric traces are frozen from fresh exposed-only calibration in 5B.',
        development_calibration_seconds=durations,unit_seconds=unit,traces=illustrative))
    dump('validation.json',dict(passed=True,scope='Offline planning checks; no GPU inference or upstream runtime integration',
        generated_unique_questions=len(generated),provisional_reserve=400,selected_unique_questions=len(sample),
        measured_outcomes=24*3*2*2,comparison_jobs=2*3,calibration_requests=2*3*2,
        repeat_is_not_independence=True,selection_disjoint=True,source_lock_verified=True,
        three_trace_rules_materialized=True,candidate_unchanged=True,
        plan_sha256=sha(HERE/'plan.json'),candidate_lock_sha256=sha(HERE/'candidate-lock.json'),
        audit_source_sha256=sha(Path(__file__)),
        implementation_gaps=['Pinned full-dataset input manifest','5B runner supporting cohort shards and trace rules','Planning-plan hash recorded by runner','Upstream contract audit before any 6C runs']))
    print('PASS: 100 exposed / 400 provisionally reserved; 24 selected; 288 planned outcomes; source lock and trace rules verified.')

if __name__=='__main__':
    build()
