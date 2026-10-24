"""Audit saved mechanical evidence; no grading, CUDA, or model dependencies."""
import argparse
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def events(root, stream):
    return [json.loads(line) for line in (root/(stream+'.jsonl')).read_text().splitlines()]


def validate(root):
    checks = []

    def check(name, condition):
        checks.append(dict(name=name, passed=bool(condition)))

    spec = json.loads((root/'spec.json').read_text())
    complete = json.loads((root/'run-complete.json').read_text())
    manifest = json.loads((root/'manifest.json').read_text())
    scheduler, worker, service = [events(root,s) for s in ['scheduler','worker','service']]
    steps = {e['step']:e for e in scheduler if e['event']=='step'}
    arrivals = {e['key']:e for e in service if e['event']=='arrival'}
    decisions = [e for e in scheduler if e['event']=='admission_decision']
    admitted = [e for e in worker if e['event']=='admitted']
    reductions = [e for e in worker if e['event']=='live_reduction']
    cues = [e for e in worker if e['event']=='cue_started']
    expected = {f"{mode}-{item['index']:02d}"
                for mode in spec['policy_order'] for item in spec['arrivals']}
    check('complete four-mode run with exact request count', complete['complete'] and
          complete['requests']==len(expected) and all(p['completed'] for p in complete['phases']))
    check('frozen trace unchanged', digest(root/'trace.json')==complete['trace_sha256'] and
          digest(root/'trace.json')==json.loads((root/'trace-freeze.json').read_text())['sha256'])
    trace = json.loads((root/'trace.json').read_text())
    check('trace matches saved specification', trace['arrivals']==spec['arrivals'] and
          trace['order']==spec['policy_order'])
    check('archived executed sources match source lock', manifest['sources']==
          json.loads((root/'source-lock.json').read_text()) and
          all(digest(root/'sources'/name)==value for name,value in manifest['sources'].items()))
    check('input hashes match manifest', all(digest(root/name)==value
          for name,value in manifest['input_hashes'].items()))
    check('exactly one scheduler admission per request', len(decisions)==len(expected) and
          {e['key'] for e in decisions}==expected)
    check('exactly one initial worker admission per request', len(admitted)==len(expected) and
          {e['key'] for e in admitted}==expected)
    check('all requests arrived exactly once', len(arrivals)==len(expected) and set(arrivals)==expected)
    check('no caps, service failures, or worker resumptions', not any(
        e['event'] in ('thinking_cap','answer_cap','failed','resumed') for e in worker+service))
    check('only live requests revised after positive generation progress', bool(reductions) and all(
        e['key'].startswith('live-') and e['tokens']>0 and e['previous_budget']>e['budget']
        for e in reductions))
    check('admission-only has no revisions', not any(e['key'].startswith('admission-') for e in reductions))

    for mode in spec['policy_order']:
        check(mode+': simultaneous scheduled requests', any(sum(
            r['key'].startswith(mode+'-') for r in step['active'])>=2 for step in steps.values()))
        check(mode+': late burst sees initial generation', all(
            any(e['event']=='generation_observed' and e['key']==f'{mode}-{i:02d}' and
                e['monotonic']<arrivals[f'{mode}-02']['monotonic'] for e in worker)
            for i in [0,1]))
        phase = next(p for p in complete['phases'] if p['policy']==mode)
        check(mode+': identical open-loop schedule', len(phase['client'])==len(spec['arrivals']) and all(
            abs(row['scheduled']-phase['epoch']-next(item['offset_seconds'] for item in spec['arrivals']
                if item['index']==row['index']))<1e-6 for row in phase['client']))

    for d in decisions:
        key, mode = d['key'], d['policy']
        step = steps[d['step']]
        waiting = [k for k in step['waiting'] if k.startswith(mode+'-')]
        a = next(e for e in admitted if e['key']==key)
        desired = (spec['short_budget'] if len(waiting)>=spec['waiting_threshold']
                   else spec['long_budget']) if mode in ('admission','live') else arrivals[key]['budget']
        first = next((s for s in scheduler if s['event']=='step' and
                      any(r['key']==key for r in s['active'])), None)
        check(key+': admission uses first scheduling step and its queue',
              first is not None and first['step']==d['step'] and d['waiting']==waiting and
              any(r['key']==key and r['computed_before']==0 for r in first['active']))
        check(key+': budget transported before generation', d['budget']==desired and
              a['initial_budget']==desired and a['admission_step']==d['step'] and a['tokens']==0 and
              d['monotonic']<=a['monotonic'] and all(e['monotonic']>=a['monotonic'] for e in worker
                  if e.get('key')==key and e['event']=='generation_observed'))
        record = json.loads((root/'requests'/f'{key}.json').read_text())
        ids, close, cue = record['token_ids'], record['close_id'], record['cue_ids']
        close_at = ids.index(close) if close in ids else -1
        check(key+': normal final with thinking closed and answer tokens',
              record['finished'] and record['finish_reason']=='stop' and close_at>=0 and
              len(ids)-close_at-1>1 and ids.count(close)==1 and record['open_id'] not in ids[close_at+1:])
        request_cues = [e for e in cues if e['key']==key]
        check(key+': exact forced cue if any', len(request_cues)<=1 and all(
              ids[e['tokens']:e['tokens']+len(cue)]==cue for e in request_cues))
        for e in request_cues:
            check(key+': answer continues after entire cue', len(ids)>e['tokens']+len(cue)+1)

    bound = []
    for r in reductions:
        step = steps[r['pressure_step']]
        check(r['key']+': live update uses recorded pressure', r['waiting']==[
              k for k in step['waiting'] if k.startswith('live-')] and
              len(r['waiting'])>=spec['waiting_threshold'])
        a = next(e for e in admitted if e['key']==r['key'])
        check(r['key']+': live update targets original request object',
              a['output_object']==r['output_object'])
        bound.extend(c for c in cues if c['key']==r['key'] and
                     c['monotonic']>=r['monotonic'] and c['tokens']>=r['budget'] and
                     c['output_object']==r['output_object'])
    check('at least one binding live cutoff after ongoing generation', bool(bound))
    for key in expected:
        rows = [r for s in steps.values() for r in s['active'] if r['key']==key]
        check(key+': no preemption and monotonic computation', all(r['preemptions']==0 for r in rows)
              and all(a['computed_after']<=b['computed_before'] for a,b in zip(rows,rows[1:])))
        blocks = [r['blocks'] for r in rows if 'blocks' in r]
        check(key+': sampled KV allocation prefixes retained', all(
            len(a)==len(b) and all(y[:len(x)]==x for x,y in zip(a,b))
            for a,b in zip(blocks,blocks[1:])))
    return dict(passed=all(c['passed'] for c in checks), checks=checks,
                requests=len(expected), live_reductions=len(reductions), binding_live_cutoffs=len(bound),
                note='Mechanical smoke only. CPU tests establish same-input initialization equality; separate GPU policies may see different queue histories.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        result = validate(args.root)
    except Exception as exc:
        result = dict(passed=False, error=type(exc).__name__+': '+str(exc))
    (args.root/'validation.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))
    raise SystemExit(0 if result['passed'] else 1)
