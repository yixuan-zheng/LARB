"""Offline mechanical/provenance audit for one reserved-validation job; no grading dependencies."""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path
from execution import digest,trace_for


def read(root,name):return json.loads((root/name).read_text())
def stream(root,name):
    path=root/name
    handle=path.open() if path.exists() else gzip.open(str(path)+'.gz','rt')
    with handle:return [json.loads(line) for line in handle]


def validate(root):
    plan,manifest,complete,trace=[read(root,n) for n in ['plan.json','manifest.json','run-complete.json','trace.json']]
    count=len(plan['sample']['shards'][manifest['shard']]['indices']); measured_count=8*count; total=measured_count+2
    assert complete['complete'] and complete['measured_requests']==measured_count and complete['calibration_requests']==2
    assert digest(root/'trace.json')==complete['trace_sha256']==read(root,'trace-freeze.json')['sha256']
    assert digest(root/'plan.json')==complete['plan_sha256']==read(root,'trace-freeze.json')['plan_sha256']
    assert all(digest(root/n)==h for n,h in manifest['input_hashes'].items())
    assert manifest['sources']==read(root,'source-lock.json')
    assert all(digest(root/'sources'/n)==h for n,h in manifest['sources'].items())
    assert all(manifest['sources'][n]==h for n,h in read(root,'candidate-lock.json')['files'].items())
    for name in ['vllm','torch','transformers']:assert manifest['versions'][name].split('+')[0]==plan['engine'][name]
    assert read(root,'runtime-fit.json')['passed']
    dataset=read(root,'dataset-manifest.json');problems=read(root,'problems100.json')
    assert digest(root/'problems100.json')==dataset['sparse_input_sha256']
    assert dataset['first_100_equal_saved'] and dataset['rows']==dataset['unique_ids']==500
    assert read(root,'exposure-audit.json')['development_only']
    assert all(i<100 for i in plan['sample']['shards'][manifest['shard']]['indices'])
    phases=complete['phases'];shard=manifest['shard'];condition=manifest['condition']
    assert [p['phase'] for p in phases]==['calib']+[f'b{b}-{mode}' for b,order in enumerate(plan['orders']) for mode in order]
    assert all(p['completed'] for p in phases) and len(phases[0]['client'])==2
    assert trace==trace_for(plan,shard,condition,phases[0],trace['frozen_monotonic'])
    assert trace['frozen_monotonic']<min(r['client_submitted'] for p in phases[1:] for r in p['client'])
    assert len(list((root/'requests').glob('*.json')))==total
    worker,scheduler,service=[stream(root,n+'.jsonl') for n in ['worker','scheduler','service']]
    steps={e['step']:e for e in scheduler if e['event']=='step'}
    decisions={e['key']:e for e in scheduler if e['event']=='admission_decision'}
    admitted={e['key']:e for e in worker if e['event']=='admitted'}
    arrivals={e['key']:e for e in service if e['event']=='arrival'}
    assert len(decisions)==sum(e['event']=='admission_decision' for e in scheduler)==total
    assert len(admitted)==sum(e['event']=='admitted' for e in worker)==total
    assert len(arrivals)==sum(e['event']=='arrival' for e in service)==total
    assert not any(e['event']=='failed' for e in service)
    events=defaultdict(list)
    for e in worker:
        if 'key' in e:events[e['key']].append(e)
    first_steps={};old={};blocks={}
    for step in steps.values():
        assert len(step['active'])<=2
        for row in step['active']:
            first_steps.setdefault(row['key'],(step['step'],row['computed_before']))
            assert row['preemptions']==0
            if row['key'] in old:assert row['computed_before']>=old[row['key']]
            old[row['key']]=row['computed_after']
            if 'blocks' in row:
                if row['key'] in blocks:
                    before=blocks[row['key']]
                    assert len(before)==len(row['blocks']) and all(b[:len(a)]==a for a,b in zip(before,row['blocks']))
                blocks[row['key']]=row['blocks']
    reductions=0;binding=0;overlap={};prompts={};rows=[];keys=set()
    for phase in phases:
        b=phase['block'];measured=b is not None
        expected=trace['arrivals_by_block'][b] if measured else [dict(index=i,offset_seconds=0) for i in plan['calibration']['indices']]
        assert phase['arrivals']==expected
        assert len(phase['client'])==len(expected)
        assert sorted(r['index'] for r in phase['client'])==sorted(r['index'] for r in expected)
        overlap[phase['phase']]=any(sum(r['key'].startswith(phase['phase']+'-') for r in s['active'])>=2 for s in steps.values())
        for client in phase['client']:
            key=client['key'];index=client['index'];assert key not in keys;keys.add(key)
            assert client['status']=='terminal'
            item=next(r for r in expected if r['index']==index)
            assert abs(client['scheduled']-phase['epoch']-item['offset_seconds'])<1e-6
            assert client['client_finished']>=client['scheduled'] and client['client_submitted']>=client['scheduled']-1e-3
            raw=read(root,f'requests/{key}.json');ids=raw['token_ids']
            assert raw['index']==index and raw['policy']==phase['policy'] and raw['seed']==6222+index
            assert raw['tokens']==len(ids)==client['tokens'] and raw['monotonic']==client['server_finished']
            assert raw['prompt'].startswith(problems[index]['problem'])
            if index in prompts:assert raw['prompt_token_ids']==prompts[index]
            prompts[index]=raw['prompt_token_ids']
            a=admitted[key];d=decisions[key];arrival=arrivals[key]
            waiting=[k for k in steps[d['step']]['waiting'] if k.startswith(phase['phase']+'-')]
            desired={'fixed2048':2048,'fixed4096':4096}.get(phase['policy'],2048 if phase['policy'] in ['admission','live'] and len(waiting)>=2 else 16384)
            assert d['budget']==a['initial_budget']==desired and d['waiting']==waiting
            assert first_steps[key]==(d['step'],0) and a['admission_step']==d['step'] and a['tokens']==0
            assert d['monotonic']<=a['monotonic']
            if arrival['pressure_step'] in steps:
                assert arrival['waiting']==[k for k in steps[arrival['pressure_step']]['waiting'] if k.startswith(phase['phase']+'-')]
            close=ids.index(raw['close_id']) if raw['close_id'] in ids else None
            assert close is None or raw['open_id'] not in ids[close+1:]
            rs=[e for e in events[key] if e['event']=='live_reduction'];cs=[e for e in events[key] if e['event']=='cue_started']
            caps=[e for e in events[key] if e['event'] in ['thinking_cap','answer_cap']]
            assert len(rs)<=1 and len(cs)<=1 and len(caps)<=1
            for cue in cs:
                if phase['policy'] in ['fixed2048','fixed4096']:assert cue['tokens']==desired
                start=cue['tokens'];assert ids[start:start+len(raw['cue_ids'])]==raw['cue_ids']
                assert cue['output_object']==a['output_object'] and phase['policy']!='full'
            for r in rs:
                assert phase['policy']=='live' and r['tokens']>0 and r['previous_budget']>r['budget']
                expected_waiting=[k for k in steps[r['pressure_step']]['waiting'] if k.startswith(phase['phase']+'-')]
                assert r['waiting']==expected_waiting and len(expected_waiting)>=2
                assert r['output_object']==a['output_object'] and (close is None or r['tokens']<=close)
            if caps:assert len(ids)==caps[0]['tokens']+1 and ids[-1]==raw['eos_id']
            if not measured:assert not caps and close is not None and ids[-1]==raw['eos_id']
            is_binding=any(c['monotonic']>=r['monotonic'] and c['tokens']>=r['budget'] for r in rs for c in cs)
            if measured:
                reductions+=len(rs);binding+=is_binding
                rows.append(dict(key=key,index=index,block=b,policy=phase['policy'],
                    initial_budget=a['initial_budget'],live_reduction=bool(rs),binding_live_cutoff=is_binding,
                    cap=caps[0]['event'] if caps else None,close_index=close,cue_start=cs[0]['tokens'] if cs else None,
                    queue_seconds=d['monotonic']-raw['received'],record_sha256=digest(root/f'requests/{key}.json')))
    assert len(keys)==total and len(rows)==measured_count
    # Load/cut observations are outcomes, not gates that select favorable workloads.
    initial_matches=sum(next(r for r in rows if (r['block'],r['policy'],r['index'])==(b,'admission',i))['initial_budget']==next(r for r in rows if (r['block'],r['policy'],r['index'])==(b,'live',i))['initial_budget'] for b in range(2) for i in plan['sample']['shards'][shard]['indices'])
    if condition=='gate':
        for policy in ['fixed2048','fixed4096']:
            assert any(r['policy']==policy and r['cue_start']==int(policy[5:]) and not r['cap'] for r in rows), 'Gate requires a complete uncapped real cutoff for '+policy
        assert all(overlap.values()), 'Gate requires real overlap in every phase'
    result=dict(passed=True,shard=shard,condition=condition,requests=total,measured_requests=measured_count,
        live_reductions=reductions,binding_live_cutoffs=binding,overlap_by_phase=overlap,
        paired_initial_budget_matches=initial_matches,paired_initial_budget_total=2*count,
        note='Caps retained as scientific failures; no-cut/low-overlap traces remain valid workload outcomes. No quality-driven continuation gate.',rows=rows)
    return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args()
    result=validate(args.root);(args.root/'mechanical-validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'},indent=2))
