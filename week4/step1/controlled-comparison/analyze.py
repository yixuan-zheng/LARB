"""Validate and grade the first complete controlled comparison offline."""
import argparse
from collections import defaultdict
import csv
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'admission-control'))
import bootstrap
sys.path.insert(0,str(bootstrap.LEGACY/'code'))
from baseline import boxed
from grade_stage3 import grade_answer
from metrics import finish_kind, outcome, summarize


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(root,name):
    return json.loads((root/name).read_text())


def lines(root,name):
    return [json.loads(line) for line in (root/name).read_text().splitlines()]


def analyze(root):
    spec,trace,complete,manifest=[read(root,n) for n in ['spec.json','trace.json','run-complete.json','manifest.json']]
    assert complete['complete'] and complete['measured_requests']==96 and complete['calibration_requests']==2
    assert digest(root/'trace.json')==complete['trace_sha256']==read(root,'trace-freeze.json')['sha256']
    assert all(digest(root/name)==sha for name,sha in manifest['input_hashes'].items())
    assert manifest['sources']==read(root,'source-lock.json')
    assert all(digest(root/'sources'/name)==sha for name,sha in manifest['sources'].items())
    assert metadata.version('math-verify')=='0.9.0'
    phases=complete['phases']
    expected_names=['calib']+[f'b{b}-{mode}' for b,order in enumerate(spec['policy_orders']) for mode in order]
    assert [p['phase'] for p in phases]==expected_names and all(p['completed'] for p in phases)
    assert all(p['arrivals']==trace['arrivals'] for p in phases[1:])
    assert all(len(p['client'])==(2 if p['block'] is None else 12) for p in phases)
    assert len({r['key'] for p in phases for r in p['client']})==98
    durations=[r['client_finished']-r['scheduled'] for r in phases[0]['client']]
    rule=spec['calibration_rule']
    assert trace['calibration_latencies_seconds']==durations
    assert trace['burst_at_seconds']==rule['burst_fraction_of_min_latency']*min(durations)
    assert trace['relative_deadline_seconds']==max(rule['minimum_deadline_seconds'],rule['deadline_multiple_of_max_latency']*max(durations))
    assert trace['arrivals']==[dict(index=i,offset_seconds=0 if i<2 else trace['burst_at_seconds']+(i-2)*.05) for i in range(12)]
    assert trace['frozen_monotonic']<min(r['client_submitted'] for p in phases[1:] for r in p['client'])
    expected_h=max(r['offset_seconds']+trace['relative_deadline_seconds'] for r in trace['arrivals'])
    assert abs(trace['observation_horizon_seconds']-expected_h)<1e-8
    worker,scheduler,service=[lines(root,n+'.jsonl') for n in ['worker','scheduler','service']]
    steps={e['step']:e for e in scheduler if e['event']=='step'}
    decisions={e['key']:e for e in scheduler if e['event']=='admission_decision'}
    admitted={e['key']:e for e in worker if e['event']=='admitted'}
    assert len(decisions)==sum(e['event']=='admission_decision' for e in scheduler)
    assert len(admitted)==sum(e['event']=='admitted' for e in worker)
    arrivals={e['key']:e for e in service if e['event']=='arrival'}
    events=defaultdict(list)
    for e in worker:
        if 'key' in e: events[e['key']].append(e)
    caps={e['key']:e['event'] for e in worker if e['event'] in ('thinking_cap','answer_cap')}
    old,blocks,first_steps={},{},{}
    for step in steps.values():
        assert len(step['active'])<=spec['max_active_sequences']
        for row in step['active']:
            first_steps.setdefault(row['key'],(step['step'],row['computed_before']))
            assert row['preemptions']==0
            if row['key'] in old:
                assert row['computed_before']>=old[row['key']]
            old[row['key']]=row['computed_after']
            if 'blocks' in row:
                if row['key'] in blocks:
                    before=blocks[row['key']]
                    assert len(before)==len(row['blocks']) and all(b[:len(a)]==a for a,b in zip(before,row['blocks']))
                blocks[row['key']]=row['blocks']
    for key,a in arrivals.items():
        phase=key.rsplit('-',1)[0]
        if a['pressure_step'] in steps:
            assert a['waiting']==[k for k in steps[a['pressure_step']]['waiting'] if k.startswith(phase+'-')]
        if a['pressure_valid']:
            assert 0<=a['pressure_age_s']<=spec['arrival_snapshot_max_age_s']
        desired=2048 if a['policy']=='arrival' and a['pressure_valid'] and len(a['waiting'])>=2 else 16384
        assert a['budget']==desired
    for key,d in decisions.items():
        phase=key.rsplit('-',1)[0]
        waiting=[k for k in steps[d['step']]['waiting'] if k.startswith(phase+'-')]
        expected=(2048 if len(waiting)>=2 else 16384) if d['policy'] in ('admission','live') else arrivals[key]['budget']
        assert d['waiting']==waiting and d['budget']==expected
        assert first_steps[key]==(d['step'],0)
        a=admitted[key]
        assert a['initial_budget']==expected and a['admission_step']==d['step'] and a['tokens']==0
        assert d['monotonic']<=a['monotonic']
    for p in phases[1:]:
        burst_arrival=arrivals[f"{p['phase']}-02"]['monotonic']
        assert all(any(e['event']=='generation_observed' and e['key']==f"{p['phase']}-{i:02d}" and
                       e['monotonic']<burst_arrival for e in worker) for i in [0,1]),'Burst before thinking began'
        assert any(sum(r['key'].startswith(p['phase']+'-') for r in s['active'])>=2 for s in steps.values())
    problems=read(root,'problems100.json')
    rows=[]
    prompts={}
    for phase in phases[1:]:
        for client in phase['client']:
            key=client['key'];index=client['index']
            item=next(r for r in trace['arrivals'] if r['index']==index)
            assert abs(client['scheduled']-phase['epoch']-item['offset_seconds'])<1e-6
            path=root/'requests'/f'{key}.json'
            raw=json.loads(path.read_text()) if path.exists() else None
            reductions=[e for e in events[key] if e['event']=='live_reduction']
            cues=[e for e in events[key] if e['event']=='cue_started']
            boundary=None;answer_tokens=None;pred=None;grade=dict(correct=False,method='missing_final',issue=None)
            if raw:
                assert raw['seed']==6222+index and raw['policy']==phase['policy']
                assert raw['tokens']==len(raw['token_ids'])==client['tokens']
                assert raw['monotonic']==client['server_finished']
                prompt=tuple(raw['prompt_token_ids'])
                if index in prompts: assert prompt==prompts[index]
                prompts[index]=prompt
                ids=raw['token_ids'];close=raw['close_id']
                boundary=ids.index(close) if close in ids else None
                answer_tokens=len(ids)-boundary-1 if boundary is not None else 0
                assert boundary is None or raw['open_id'] not in ids[boundary+1:]
                assert len(cues)<=1 and len(reductions)<=1
                for cue in cues:
                    start=cue['tokens']
                    assert ids[start:start+len(raw['cue_ids'])]==raw['cue_ids']
                    assert cue['output_object']==admitted[key]['output_object']
                    assert phase['policy']!='full'
                for r in reductions:
                    assert phase['policy']=='live' and r['tokens']>0 and r['previous_budget']>r['budget']
                    expected=[k for k in steps[r['pressure_step']]['waiting'] if k.startswith(phase['phase']+'-')]
                    assert r['waiting']==expected and len(expected)>=2
                    assert r['output_object']==admitted[key]['output_object']
                    assert boundary is None or r['tokens']<=boundary
                if key in caps:
                    cap=next(e for e in events[key] if e['event']==caps[key])
                    assert len(ids)==cap['tokens']+1 and ids[-1]==raw['eos_id']
                post=raw['raw_output'].split('</think>',1)[1] if '</think>' in raw['raw_output'] else ''
                pred=boxed(post)
                grade=grade_answer(str(problems[index]['answer']),pred)
            finish=finish_kind(raw,caps.get(key))
            if client['status']!='terminal': finish=client['status']
            elapsed=client['client_finished']-client['scheduled'] if 'client_finished' in client else None
            binding=any(c['monotonic']>=r['monotonic'] and c['tokens']>=r['budget']
                        for r in reductions for c in cues)
            row=dict(block=phase['block'],policy=phase['policy'],index=index,key=key,
                reference=str(problems[index]['answer']),extracted_answer=pred,grading=grade,finish=finish,
                client_completion_seconds=elapsed,
                queue_seconds=decisions[key]['monotonic']-raw['received'] if raw and key in decisions else None,
                thinking_tokens=cues[0]['tokens'] if cues else boundary if boundary is not None else (len(raw['token_ids']) if raw else None),
                cue_tokens=len(raw['cue_ids']) if raw and cues else 0,
                output_tokens=raw['tokens'] if raw else None,
                answer_tokens=len(raw['token_ids'])-cues[0]['tokens']-len(raw['cue_ids']) if raw and cues else answer_tokens,
                live_reduction=bool(reductions),binding_live_cutoff=binding,
                initial_budget=admitted[key]['initial_budget'] if key in admitted else None,
                injection_lag_ms=client['injection_lag_ms'],record_sha256=digest(path) if path.exists() else None,
                server_ready_seconds=raw['monotonic']-raw['received'] if raw else None,
                **outcome(grade['correct'],finish,elapsed,trace['relative_deadline_seconds']))
            rows.append(row)
    assert len(rows)==96
    policies=['full','arrival','admission','live']
    summaries=[dict(block=b,policy=mode,**summarize([r for r in rows if r['block']==b and r['policy']==mode],expected_h))
               for b in range(2) for mode in policies]
    aggregate=[dict(policy=mode,**summarize([r for r in rows if r['policy']==mode],2*expected_h)) for mode in policies]
    indexed={(r['block'],r['policy'],r['index']):r for r in rows}
    paired=[]
    for b in range(2):
        for i in range(12):
            a,l=indexed[b,'admission',i],indexed[b,'live',i]
            paired.append(dict(block=b,index=i,deadline_delta=int(l['correct_on_time'])-int(a['correct_on_time']),
                               correctness_delta=int(l['completed_correct'])-int(a['completed_correct']),
                               admission_key=a['key'],live_key=l['key'],live_binding_cutoff=l['binding_live_cutoff']))
    per_block=[]
    for b in range(2):
        group=[p for p in paired if p['block']==b]
        per_block.append(dict(block=b,deadline_delta=sum(p['deadline_delta'] for p in group),
                              correctness_delta=sum(p['correctness_delta'] for p in group),
                              binding_live_cutoffs=sum(p['live_binding_cutoff'] for p in group)))
    screen=dict(deadline_gain=sum(p['deadline_delta'] for p in paired)>0,
                no_block_deadline_loss=all(p['deadline_delta']>=0 for p in per_block),
                binding_each_block=all(p['binding_live_cutoffs']>0 for p in per_block),
                quality_loss_within_plan=all(p['correctness_delta']>=-1 for p in per_block))
    return dict(complete=True,validation_passed=True,unique_problems=12,request_outcomes=96,
                trace=trace,summary=summaries,aggregate=aggregate,paired_live_vs_admission=paired,
                block_deltas=per_block,continuation_screen=screen,screen_passed=all(screen.values()),rows=rows,
                uncertainty='Two order-reversed replays of the same 12 development questions, not independent accuracy samples')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args()
    result=analyze(args.root)
    out=args.root/'analysis';out.mkdir(exist_ok=True)
    (out/'summary.json').write_text(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2)+'\n')
    (out/'graded.json').write_text(json.dumps(result['rows'],indent=2)+'\n')
    review=[r for r in result['rows'] if r['grading']['issue'] or not r['completed_correct']]
    (out/'review-queue.json').write_text(json.dumps(review,indent=2)+'\n')
    (out/'analysis-manifest.json').write_text(json.dumps(dict(versions={n:metadata.version(n) for n in
        ['math-verify','sympy','latex2sympy2_extended','antlr4-python3-runtime','mpmath']},
        sources={str(p.resolve().relative_to(bootstrap.REPO)):digest(p) for p in [Path(__file__),Path(__file__).with_name('metrics.py'),
                                           bootstrap.LEGACY/'code/grade_stage3.py',bootstrap.LEGACY/'code/baseline.py']}),indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k not in ['rows','paired_live_vs_admission']},indent=2))
