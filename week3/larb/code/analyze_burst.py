"""Audit and grade a completed frozen burst pilot; CPU only."""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import platform
import statistics

from baseline import boxed
from grade_stage3 import grade_answer


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True)
    args=ap.parse_args();root=args.root
    spec=json.loads((root/'spec.json').read_text())
    trace=json.loads((root/'trace.json').read_text())
    complete=json.loads((root/'run-complete.json').read_text())
    manifest=json.loads((root/'manifest.json').read_text())
    freeze=json.loads((root/'trace-freeze.json').read_text())
    assert complete['complete'] and complete['measured_attempts']==36
    assert digest(root/'spec.json')==manifest['spec_sha256']
    assert digest(root/'trace.json')==freeze['sha256']==complete['trace_sha256']
    for name,sha in manifest['sources'].items():
        assert digest(root/name)==sha,name
    worker=lines(root/'worker.jsonl');scheduler=lines(root/'scheduler.jsonl')
    service=lines(root/'service.jsonl')
    phases={p['phase']:p for p in complete['phases']}
    assert list(phases)==['calib']+spec['policy_order']
    assert all(phases[p]['arrivals']==trace['arrivals'] for p in spec['policy_order'])
    measured_arrivals=[e for e in service if e['event']=='arrival' and e['policy'] in spec['policy_order'] and not e['key'].startswith('calib-')]
    assert len(measured_arrivals)==36
    assert trace['frozen_monotonic']<min(e['monotonic'] for e in measured_arrivals)
    admissions={}
    events=defaultdict(list)
    for event in worker:
        if 'key' in event:
            events[event['key']].append(event)
        if event['event']=='admitted':
            assert event['key'] not in admissions,'Request admitted twice'
            admissions[event['key']]=event
    assert len(admissions)==38
    caps={e['key']:e['event'] for e in worker if e['event'] in ('thinking_cap','answer_cap')}
    live=[e for e in worker if e['event']=='live_reduction']
    assert all(e['key'].startswith('live-') and len(e['waiting'])>=2 for e in live)
    snapshots={e['step']:e for e in scheduler}
    for event in live:
        expected=[k for k in snapshots[event['pressure_step']]['waiting'] if k.startswith('live-')]
        assert event['waiting']==expected
    for event in measured_arrivals:
        phase=event['key'].rsplit('-',1)[0]
        snapshot=snapshots[event['pressure_step']]
        assert event['waiting_before']==[k for k in snapshot['waiting'] if k.startswith(phase+'-')]
    cues=[e for e in worker if e['event']=='cue_started']
    assert all(not e['key'].startswith(('full-','calib-')) for e in cues)
    old={};blocks={};max_active=0
    for step in scheduler:
        max_active=max(max_active,len(step['active']))
        assert len(step['active'])<=2
        for row in step['active']:
            assert row['preemptions']==0
            if row['key'] in old:
                assert row['computed_before']>=old[row['key']]['computed_after']
            old[row['key']]=row
            if 'blocks' in row:
                assert row['blocks'] and all(row['blocks'])
                if row['key'] in blocks:
                    previous=blocks[row['key']]
                    assert len(previous)==len(row['blocks'])
                    assert all(current[:len(prior)]==prior for prior,current in zip(previous,row['blocks']))
                blocks[row['key']]=row['blocks']
    manual_path=root/'manual-review.json'
    manual=json.loads(manual_path.read_text()) if manual_path.exists() else []
    corrections={(r['policy'],r['index']):r for r in manual}
    problems=json.loads((root/'problems100.json').read_text())
    rows=[]
    for policy in ['full','arrival','live']:
        phase=phases[policy]
        clients={r['index']:r for r in phase['client']}
        assert sorted(clients)==list(range(12))
        for index in range(12):
            key=f'{policy}-{index:02d}';path=root/'requests'/f'{key}.json'
            raw=json.loads(path.read_text());client=clients[index]
            assert raw['seed']==6222+index and raw['policy']==policy
            assert raw['reference']==str(problems[index]['answer'])
            assert len(raw['token_ids'])==raw['tokens']==client['tokens']
            assert raw['monotonic']==client['server_finished']
            received=next(e for e in service if e['event']=='arrival' and e['key']==key)
            initial=2048 if policy!='full' and len(received['waiting_before'])>=2 else 16384
            assert raw['initial_budget']==initial==received['budget']==admissions[key]['initial_budget']
            ids=raw['token_ids'];close=raw['close_id']
            boundary=ids.index(close) if close in ids else None
            post=raw['raw_output'].split('</think>',1)[1] if '</think>' in raw['raw_output'] else ''
            pred=boxed(post)
            grade=grade_answer(raw['reference'],pred)
            correction=corrections.get((policy,index))
            if correction:
                assert correction['record_sha256']==digest(path)
            correct=correction['correct'] if correction else grade['correct']
            finish=caps.get(key, 'eos' if raw['finish_reason']=='stop' and boundary is not None and ids[-1]==raw['eos_id'] else 'missing_thinking_close' if raw['finish_reason']=='stop' and boundary is None else str(raw['finish_reason']))
            if key in caps:
                cap_event=next(e for e in events[key] if e['event']==caps[key])
                assert len(ids)==cap_event['tokens']+1 and ids[-1]==raw['eos_id']
                if finish=='thinking_cap':
                    assert boundary is None and cap_event['tokens']==16384
                else:
                    assert boundary is not None and cap_event['tokens']-boundary-1==2048
            else:
                if boundary is not None:
                    assert len(ids)-boundary-1<=2048
                else:
                    assert finish=='missing_thinking_close' and len(ids)<=16384
            if boundary is not None:
                assert raw['open_id'] not in ids[boundary+1:],'Thinking reopened'
            forced=[e for e in events[key] if e['event']=='cue_started']
            assert len(forced)<=1
            for event in forced:
                start=event['tokens'];cue=raw['cue_ids']
                assert ids[start:start+len(cue)]==cue
                assert event['budget']==2048 and start>=2048
                if policy=='arrival':
                    assert initial==2048 and start==2048
            completed=correct and finish=='eos'
            elapsed=raw['monotonic']-client['scheduled']
            client_elapsed=client['client_finished']-client['scheduled']
            normal=finish=='eos'
            reduction=[e for e in events[key] if e['event']=='live_reduction']
            assert len(reduction)<=1
            rows.append(dict(policy=policy,index=index,key=key,reference=raw['reference'],
                extracted_answer=pred,grading=grade,manual_review=correction,
                completed_correct=completed,normal_completion=normal,finish_reason=finish,
                on_time=elapsed<=trace['relative_deadline_seconds'],
                correct_on_time=completed and elapsed<=trace['relative_deadline_seconds'],
                client_correct_on_time=completed and client_elapsed<=trace['relative_deadline_seconds'],
                completion_seconds=elapsed,client_completion_seconds=client_elapsed,
                queue_seconds=admissions[key]['monotonic']-raw['received'],
                first_token_seconds=raw['first_token']-client['scheduled'],
                injection_lag_ms=client['injection_lag_ms'],
                scheduled_offset_seconds=client['scheduled']-phase['epoch'],
                admitted_offset_seconds=admissions[key]['monotonic']-phase['epoch'],
                completed_offset_seconds=raw['monotonic']-phase['epoch'],
                output_tokens=len(ids),initial_budget=initial,cue_started=bool(forced),
                live_reduction_tokens=reduction[0]['tokens'] if reduction else None,
                genuine_live_cutoff=bool(reduction and reduction[0]['tokens']>0 and forced),
                record_sha256=digest(path)))
    assert len(list((root/'requests').glob('*.json')))==38
    prefix_checks=[]
    for index in range(12):
        records={p:json.loads((root/'requests'/f'{p}-{index:02d}.json').read_text())
                 for p in ['full','arrival','live']}
        assert len({tuple(r['prompt_token_ids']) for r in records.values()})==1
        assert len({r['reference'] for r in records.values()})==1
        for policy in ['arrival','live']:
            left=records['full']['token_ids'];right=records[policy]['token_ids']
            key=f'{policy}-{index:02d}'
            starts=[e['tokens'] for e in events[key] if e['event']=='cue_started']
            limit=min(len(left),len(right),starts[0] if starts else 16384)
            for record in [records['full'],records[policy]]:
                if record['close_id'] in record['token_ids']:
                    limit=min(limit,record['token_ids'].index(record['close_id']))
            common=next((i for i in range(limit) if left[i]!=right[i]),limit)
            prefix_checks.append(dict(index=index,policy=policy,compared_tokens=limit,
                common_prefix_tokens=common,matched_before_cut_or_natural_close=common==limit))
    summary=[]
    for policy in ['full','arrival','live']:
        group=[r for r in rows if r['policy']==policy]
        correct=sum(r['completed_correct'] for r in group)
        timely=sum(r['correct_on_time'] for r in group)
        summary.append(dict(policy=policy,n=12,completed_correct=correct,
            accuracy_percent=100*correct/12,correct_on_time=timely,
            client_correct_on_time=sum(r['client_correct_on_time'] for r in group),
            deadline_goodput_per_minute=60*timely/trace['fixed_observation_horizon_seconds'],
            median_completion_seconds=statistics.median(r['completion_seconds'] for r in group),
            mean_completion_seconds=statistics.mean(r['completion_seconds'] for r in group),
            mean_queue_seconds=statistics.mean(r['queue_seconds'] for r in group),
            drain_seconds=max(r['completed_offset_seconds'] for r in group),
            normal_completions=sum(r['normal_completion'] for r in group),
            finish_counts=dict(Counter(r['finish_reason'] for r in group)),
            initial_short_budgets=sum(r['initial_budget']==2048 for r in group),
            cue_starts=sum(r['cue_started'] for r in group),
            live_reductions=sum(r['live_reduction_tokens'] is not None for r in group),
            genuine_live_cutoffs=sum(r['genuine_live_cutoff'] for r in group),
            max_injection_lag_ms=max(r['injection_lag_ms'] for r in group)))
    by={r['policy']:r for r in summary}
    screen=dict(genuine_live_cutoff=by['live']['genuine_live_cutoffs']>0,
        more_correct_on_time_than_both=by['live']['correct_on_time']>max(by['full']['correct_on_time'],by['arrival']['correct_on_time']),
        no_fewer_completed_correct_than_full=by['live']['completed_correct']>=by['full']['completed_correct'])
    paired={}
    indexed={(r['policy'],r['index']):r for r in rows}
    for policy in ['arrival','live']:
        paired[policy]={
            'correctness_losses':[i for i in range(12) if indexed['full',i]['completed_correct'] and not indexed[policy,i]['completed_correct']],
            'correctness_gains':[i for i in range(12) if not indexed['full',i]['completed_correct'] and indexed[policy,i]['completed_correct']],
            'new_correct_on_time':[i for i in range(12) if not indexed['full',i]['correct_on_time'] and indexed[policy,i]['correct_on_time']],
            'lost_correct_on_time':[i for i in range(12) if indexed['full',i]['correct_on_time'] and not indexed[policy,i]['correct_on_time']]}
    out=root/'analysis';out.mkdir(exist_ok=True)
    (out/'graded.json').write_text(json.dumps(rows,indent=2)+'\n')
    result=dict(summary=summary,screen=screen,screen_passed=all(screen.values()),trace=trace,
        paired_vs_full=paired,
        max_active=max_active,measured_records=36,calibration_records=2,
        row_move_events=sum(e['event']=='row_move' for e in worker),
        matched_prefixes=sum(r['matched_before_cut_or_natural_close'] for r in prefix_checks),
        compared_prefixes=len(prefix_checks),
        validation='Complete records and source hashes; identical frozen trace; pressure rules, cue sequences, caps, no reopening, monotonic computation, retained sampled KV prefixes, zero preemption verified')
    (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    (out/'prefix-checks.json').write_text(json.dumps(prefix_checks,indent=2)+'\n')
    columns=[k for k in rows[0] if k not in ('grading','manual_review')]
    with (out/'per-request.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
    (out/'review-queue.json').write_text(json.dumps([r for r in rows if not r['completed_correct'] or r['grading']['issue']],indent=2)+'\n')
    versions={p:metadata.version(p) for p in ['math-verify','sympy','latex2sympy2_extended','numpy','matplotlib']}
    (out/'analysis-manifest.json').write_text(json.dumps(dict(versions=versions,python=platform.python_version(),
        sources={p.name:digest(p) for p in [Path(__file__),Path(__file__).with_name('grade_stage3.py'),Path(__file__).with_name('baseline.py')]},
        spec_sha256=digest(root/'spec.json'),trace_sha256=digest(root/'trace.json'),
        manual_sha256=digest(manual_path) if manual_path.exists() else None),indent=2)+'\n')
    # A static timeline is an audit aid, not an additional experiment.
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    fig,axes=plt.subplots(1,3,figsize=(13,5),sharex=True,sharey=True)
    for axis,policy in zip(axes,['full','arrival','live']):
        for r in [x for x in rows if x['policy']==policy]:
            i=r['index'];start=r['scheduled_offset_seconds'];admit=r['admitted_offset_seconds'];end=r['completed_offset_seconds']
            color='#258552' if r['correct_on_time'] else '#d89b22' if r['completed_correct'] else '#bd4141'
            axis.barh(i,admit-start,left=start,color='#d9dce1',height=.6)
            axis.barh(i,end-admit,left=admit,color=color,height=.6)
            axis.plot(start+trace['relative_deadline_seconds'],i,marker='|',color='black',ms=10)
        axis.axvline(trace['burst_at_seconds'],color='#777',ls=':',lw=1)
        axis.set_title({'full':'Full thinking','arrival':'Arrival-only budget','live':'Live budget updates'}[policy])
        axis.set_xlabel('Seconds from trace start');axis.grid(axis='x',alpha=.15)
    axes[0].set_yticks(range(12));axes[0].invert_yaxis();axes[0].set_ylabel('Problem index')
    fig.legend(handles=[Patch(color='#d9dce1',label='Queued'),Patch(color='#258552',label='Correct and on time'),Patch(color='#d89b22',label='Correct but late'),Patch(color='#bd4141',label='Wrong or capped')],loc='lower center',ncol=4)
    fig.suptitle('One frozen development burst; black ticks mark per-request deadlines')
    fig.tight_layout(rect=(0,.07,1,.94));fig.savefig(out/'timeline.png',dpi=160);fig.savefig(out/'timeline.pdf');plt.close(fig)
    print(json.dumps(dict(summary=summary,screen=screen,screen_passed=all(screen.values())),indent=2))


if __name__=='__main__':
    main()
