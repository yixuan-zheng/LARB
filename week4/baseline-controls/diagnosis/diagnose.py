"""Saved-record descriptive diagnosis. No model execution, submission, or policy edits."""
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAMPAIGN = HERE.parent

def read(p): return json.loads(p.read_text())

def main():
    conditions = []
    for job in ['6512259', '6512260']:
        root = CAMPAIGN/'results'/('job-'+job)
        rows = read(root/'analysis/graded.json')
        run = read(root/'run-complete.json')
        events = [json.loads(line) for line in (root/'worker.jsonl').read_text().splitlines()]
        by_key = {r['key']:r for r in rows}
        phases = {p['phase']:p for p in run['phases'][1:]}
        clients = {c['key']:c for p in phases.values() for c in p['client']}
        pairs = []
        for live in [r for r in rows if r['policy']=='live']:
            fixed = next(r for r in rows if r['policy']=='fixed2048' and r['index']==live['index'] and r['block']==live['block'])
            def detail(r):
                es = [e for e in events if e.get('key')==r['key']]
                admitted = next(e for e in es if e['event']=='admitted')
                closed = next(e for e in es if e['event']=='thinking_closed')
                reductions = [dict(tokens=e['tokens'],waiting=len(e['waiting']),seconds_after_admission=e['monotonic']-admitted['monotonic'],pressure_age_ms=e['pressure_age_ms'],tokens_over_short=max(0,e['tokens']-2048)) for e in es if e['event']=='live_reduction']
                c=clients[r['key']]
                return dict(key=r['key'],initial_budget=r['initial_budget'],admission_waiting=len(admitted['waiting']),queue_seconds=r['queue_seconds'],completion_seconds=r['client_completion_seconds'],first_token_seconds=c['client_first']-c['scheduled'],post_first_token_seconds=c['client_finished']-c['client_first'],thinking_seconds_after_admission=closed['monotonic']-admitted['monotonic'],thinking_tokens=r['thinking_tokens'],output_tokens=r['output_tokens'],answer_tokens=r['answer_tokens'],correct=r['completed_correct'],on_time=r['correct_on_time'],extracted=r['extracted_answer'],reference=r['reference'],forced=closed['forced'],binding_cut=r['binding_live_cutoff'],reductions=reductions)
            for original in [live,fixed]:
                request_path=root/'requests'/(original['key']+'.json')
                assert hashlib.sha256(request_path.read_bytes()).hexdigest()==original['record_sha256']
            raw_live=read(root/'requests'/(live['key']+'.json'));raw_fixed=read(root/'requests'/(fixed['key']+'.json'))
            prefix=next((i for i,(a,b) in enumerate(zip(raw_live['token_ids'],raw_fixed['token_ids'])) if a!=b), min(len(raw_live['token_ids']),len(raw_fixed['token_ids'])))
            assert raw_live['prompt_token_ids']==raw_fixed['prompt_token_ids'] and raw_live['seed']==raw_fixed['seed']
            pairs.append(dict(common_output_prefix_tokens=prefix,same_prompt_and_seed=True,index=live['index'],block=live['block'],live=detail(live),fixed=detail(fixed),extra_thinking_tokens=live['thinking_tokens']-fixed['thinking_tokens'],extra_output_tokens=live['output_tokens']-fixed['output_tokens'],completion_delta_seconds=live['client_completion_seconds']-fixed['client_completion_seconds'],queue_delta_seconds=live['queue_seconds']-fixed['queue_seconds'],correctness_delta=int(live['completed_correct'])-int(fixed['completed_correct']),on_time_delta=int(live['correct_on_time'])-int(fixed['correct_on_time'])))
        # Integrate scheduler waiting-list length over each measured phase.
        stats={name:dict(queue_request_seconds=0.0,waiting_at_least_one_seconds=0.0,waiting_at_least_two_seconds=0.0,max_waiting=0,single_waiter_long_budget_seconds=0.0) for name in phases}
        previous={}
        with gzip.open(root/'scheduler.jsonl.gz','rt') as stream:
            for line in stream:
                e=json.loads(line)
                if e['event']!='step': continue
                keys=e['waiting']+[a['key'] for a in e['active']]
                names={k.rsplit('-',1)[0] for k in keys}
                # Include last interval until next step (including empty final step).
                for name,old in list(previous.items()):
                    phase=phases[name];end=max(c['client_finished'] for c in phase['client'])
                    t=min(e['monotonic'],end);dt=max(0,t-old['monotonic'])
                    n=sum(k.startswith(name+'-') for k in old['waiting'])
                    s=stats[name];s['queue_request_seconds']+=n*dt;s['waiting_at_least_one_seconds']+=(n>0)*dt;s['waiting_at_least_two_seconds']+=(n>=2)*dt;s['max_waiting']=max(s['max_waiting'],n)
                    long_active=[]
                    for active in old['active']:
                        r=by_key.get(active['key'])
                        if r and r['initial_budget']>2048:
                            reductions=[x for x in events if x.get('key')==r['key'] and x['event']=='live_reduction' and x['monotonic']<=old['monotonic']]
                            closes=[x for x in events if x.get('key')==r['key'] and x['event']=='thinking_closed' and x['monotonic']<=old['monotonic']]
                            if not reductions and not closes:long_active.append(r['key'])
                    if n==1 and long_active:s['single_waiter_long_budget_seconds']+=dt
                    del previous[name]
                for name in names:
                    if name in phases:previous[name]=e
        reductions=[dict(index=p['index'],block=p['block'],binding=p['live']['binding_cut'],**r) for p in pairs for r in p['live']['reductions']]
        summary=dict(extra_thinking_pairs=sum(p['extra_thinking_tokens']>0 for p in pairs),extra_thinking_tokens_positive=sum(max(0,p['extra_thinking_tokens']) for p in pairs),accuracy_gains=sum(p['correctness_delta']>0 for p in pairs),accuracy_losses=sum(p['correctness_delta']<0 for p in pairs),on_time_gains=sum(p['on_time_delta']>0 for p in pairs),on_time_losses=sum(p['on_time_delta']<0 for p in pairs),reductions=len(reductions),nonbinding=sum(not r['binding'] for r in reductions),reductions_after_short=sum(r['tokens']>2048 for r in reductions),tokens_already_over_short=sum(r['tokens_over_short'] for r in reductions),max_pressure_age_ms=max(r['pressure_age_ms'] for r in reductions))
        assert len(pairs)==24 and len({(p['block'],p['index']) for p in pairs})==24
        assert len(reductions)==sum(r['live_reduction'] for r in rows if r['policy']=='live')
        for p in pairs:
            for role in ['live','fixed']:
                d=p[role];assert abs(d['first_token_seconds']+d['post_first_token_seconds']-d['completion_seconds'])<1e-6
        conditions.append(dict(job=job,condition=rows[0]['condition'],deadline_seconds=read(root/'trace.json')['relative_deadline_seconds'],summary=summary,pairs=pairs,reductions=reductions,queue_integrals=stats,input_sha256={f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in ['analysis/graded.json','worker.jsonl','scheduler.jsonl.gz','run-complete.json']}))
    output=dict(conditions=conditions,notes=['Descriptive matched question/block comparisons, not isolated causal cut effects.','Worker-relative intervals use worker clocks; client latency uses client clocks. Scheduler integrals use consecutive scheduler snapshots and are sampled occupancy, not client wait estimates.','A single-waiter long-budget interval includes active thinking before closure, even below 2048; it diagnoses the trigger blind spot rather than proving wasted thinking.'])
    (HERE/'diagnosis.json').write_text(json.dumps(output,indent=2)+'\n')
    for c in conditions:
        print(c['condition'],c['summary']);print('cuts',c['reductions']);print('queues',c['queue_integrals'])
        for p in c['pairs']:
            if p['index'] in [1,94]:print(json.dumps(p))

if __name__=='__main__': main()
