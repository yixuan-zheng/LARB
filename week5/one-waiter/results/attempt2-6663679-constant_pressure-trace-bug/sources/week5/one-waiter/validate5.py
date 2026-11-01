"""Mechanical and provenance audit for one Week 5 job; no grading dependencies.

Coverage is reported honestly: a truncated run is valid evidence for the phases
it completed and is never treated as the frozen 576-outcome design.
"""
import argparse
from collections import defaultdict
import gzip
import json
from pathlib import Path

from execution import digest


def read(root, name):
    return json.loads((root / name).read_text())


def stream(root, name):
    path = root / name
    handle = path.open() if path.exists() else gzip.open(str(path) + '.gz', 'rt')
    with handle:
        return [json.loads(line) for line in handle]


def validate(root):
    failures = []
    plan, manifest, complete, trace = [read(root, n) for n in
                                       ['plan.json', 'manifest.json', 'run-complete.json',
                                        'trace.json']]
    cohort_doc = read(root, 'cohort.json')

    def check(condition, message):
        if not condition:
            failures.append(message)

    check(digest(root / 'trace.json') == complete['trace_sha256']
          == read(root, 'trace-freeze.json')['sha256'], 'trace hash mismatch')
    check(digest(root / 'plan.json') == complete['plan_sha256']
          == read(root, 'trace-freeze.json')['plan_sha256'], 'plan hash mismatch')
    check(all(digest(root / n) == h for n, h in manifest['input_hashes'].items()),
          'input hash mismatch')
    check(manifest['sources'] == read(root, 'source-lock.json'), 'source lock mismatch')
    check(all(digest(root / 'sources' / n) == h for n, h in manifest['sources'].items()),
          'executed source hash mismatch')
    for name in ['vllm', 'torch', 'transformers']:
        check(manifest['versions'][name].split('+')[0] == plan['engine'][name],
              'runtime mismatch: ' + name)
    used = set(plan['cohort']['used_indices'])
    check(not used & set(plan['cohort']['rank_order']), 'cohort reuses an exposed Week 3/4 index')
    check(set(plan['cohort']['rank_order']) <= set(range(100)), 'cohort outside the 0-99 pool')
    check(plan['cohort']['rank_order'] == cohort_doc['cohort_rank_order'], 'cohort rule mismatch')

    phases = complete['phases']
    measured = [p for p in phases if p['phase'].startswith('b') and p['completed']]
    check(phases[0]['phase'] == 'calib' and phases[0]['completed'], 'calibration incomplete')
    check(all(p['completed'] for p in phases), 'a saved phase did not complete')
    check(trace['frozen_monotonic'] < min(r['client_submitted'] for p in phases[1:]
                                          for r in p['client']), 'trace frozen after measurement')

    worker, scheduler, service = [stream(root, n + '.jsonl') for n in
                                  ['worker', 'scheduler', 'service']]
    steps = {e['step']: e for e in scheduler if e['event'] == 'step'}
    decisions = {e['key']: e for e in scheduler if e['event'] == 'admission_decision'}
    admitted = {e['key']: e for e in worker if e['event'] == 'admitted'}
    arrivals = {e['key']: e for e in service if e['event'] == 'arrival'}
    firsts = {e['key']: e for e in service if e['event'] == 'first_token'}
    total = sum(len(p['client']) for p in phases)
    check(len(decisions) == total, 'missing admission decisions')
    check(len(admitted) == total, 'missing worker admissions')
    check(len(arrivals) == total, 'missing client arrivals')
    check(not any(e['event'] == 'failed' for e in service), 'service failure recorded')
    check(len(list((root / 'requests').glob('*.json'))) == total, 'missing request records')

    events = defaultdict(list)
    for e in worker:
        if 'key' in e:
            events[e['key']].append(e)
    rows, reductions, binding, overlap = [], 0, 0, {}
    for phase in measured:
        name, policy = phase['phase'], phase['policy']
        phase_keys = {c['key'] for c in phase['client']}
        counts = [len({row['key'] for row in s['active']} & phase_keys)
                  for s in steps.values()]
        overlap[name] = max(counts) if counts else 0
        expected_trigger = (plan['budget']['waiting_threshold_live_one'] if policy == 'live_one'
                            else plan['budget']['waiting_threshold_live']
                            if policy == 'live' else None)
        for client in phase['client']:
            key, index = client['key'], client['index']
            check(key in decisions and key in admitted and key in firsts,
                  'missing events for ' + key)
            if key not in decisions or key not in admitted or key not in firsts:
                continue
            decision = decisions[key]
            check(decision['step'] <= admitted[key]['admission_step'],
                  'admission decision after worker admission: ' + key)
            check(decision.get('trigger') == expected_trigger, 'trigger metadata wrong: ' + key)
            check(firsts[key]['monotonic'] > decision['monotonic'],
                  'budget decision did not precede generation: ' + key)
            raw = read(root, f'requests/{key}.json')
            ids = raw['token_ids']
            check(client['status'] == 'terminal', 'non-terminal client row: ' + key)
            check(raw['policy'] == policy and raw['index'] == index, 'record identity: ' + key)
            close = ids.index(raw['close_id']) if raw['close_id'] in ids else None
            check(close is None or raw['open_id'] not in ids[close + 1:], 'thinking reopened: ' + key)
            cue_starts = [e for e in events[key] if e['event'] == 'cue_started']
            caps = [e for e in events[key] if e['event'] in ('thinking_cap', 'answer_cap')]
            live = [e for e in events[key] if e['event'] == 'live_reduction']
            check(len(cue_starts) <= 1 and len(caps) <= 1, 'duplicate transition: ' + key)
            if cue_starts:
                start = cue_starts[0]['tokens']
                check(ids[start:start + len(raw['cue_ids'])] == raw['cue_ids'],
                      'cue token sequence wrong: ' + key)
                offset = raw['cue_ids'].index(raw['close_id'])
                check(close is not None and close == start + offset,
                      'cue did not close thinking at the recorded index: ' + key)
                check(cue_starts[0]['output_object'] == admitted[key]['output_object'],
                      'transition did not reuse the admitted request state: ' + key)
            for reduction in live:
                check(policy in ('live', 'live_one'), 'fixed policy cut a request: ' + key)
                check(reduction['tokens'] > 0 and
                      reduction['previous_budget'] > reduction['budget'],
                      'invalid reduction: ' + key)
                check(len(reduction['waiting']) >= expected_trigger,
                      'reduction below its own trigger: ' + key)
                check(reduction['output_object'] == admitted[key]['output_object'],
                      'reduction lost request identity: ' + key)
                check(close is None or reduction['tokens'] <= close,
                      'reduction after natural closure: ' + key)
                if decision['waiting']:
                    check(len(decision['waiting']) >= expected_trigger,
                          'admission budget below its own trigger: ' + key)
                elif expected_trigger is not None:
                    check(decision['budget'] == plan['budget']['long'],
                          'unpressured admission was not given the long budget: ' + key)
            if caps:
                check(len(ids) == caps[0]['tokens'] + 1 and ids[-1] == raw['eos_id'],
                      'cap boundary mismatch: ' + key)
            is_binding = any(c['tokens'] >= r['budget'] and c['monotonic'] >= r['monotonic']
                             for r in live for c in cue_starts)
            reductions += len(live)
            binding += is_binding
            rows.append(dict(key=key, index=index, block=phase['block'], policy=policy,
                             initial_budget=admitted[key]['initial_budget'],
                             trigger=decision.get('trigger'),
                             admission_waiting=decision.get('waiting'),
                             live_reduction=bool(live), binding_live_cutoff=is_binding,
                             reduction_waiting=live[0]['waiting'] if live else [],
                             reduction_tokens=live[0]['tokens'] if live else None,
                             cap=caps[0]['event'] if caps else None, close_index=close,
                             cue_start=cue_starts[0]['tokens'] if cue_starts else None,
                             output_tokens=len(ids),
                             request_sha256=digest(root / f'requests/{key}.json')))
    if complete['condition'] in ('gate', 'constant_pressure', 'slack_rush_recovery'):
        check(any(value >= 2 for value in overlap.values()),
              'no phase ran two requests concurrently')
    if complete['condition'] == 'gate':
        check(any(r['policy'] == 'live_one' and r['binding_live_cutoff'] for r in rows),
              'gate: no binding one-waiter cut')
        check(any(r['policy'] == 'fixed2048' and r['cue_start'] == 2048 and not r['cap']
                  for r in rows), 'gate: no complete fixed-2048 transition')
    return dict(passed=not failures, failures=failures, condition=complete['condition'],
                requests=total, measured_requests=sum(len(p['client']) for p in measured),
                phases_completed=[p['phase'] for p in measured], skipped=complete['skipped'],
                live_reductions=reductions, binding_live_cutoffs=binding,
                overlap_by_phase=overlap, rows=rows,
                coverage=dict(questions=len({r['index'] for r in rows}),
                              frozen_intent=plan['coverage'],
                              truncated=bool(complete['skipped'])),
                note='Caps and wrong answers are scientific outcomes; partial coverage is reported.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    result = validate(args.root)
    (args.root / 'mechanical-validation.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}, indent=2))
    raise SystemExit(0 if result['passed'] else 1)
