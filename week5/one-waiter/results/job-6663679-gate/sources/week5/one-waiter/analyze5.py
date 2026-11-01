"""Grade one Week 5 job and report per-workload policy comparisons and verdicts."""
import argparse
import importlib.metadata as metadata
import json
from pathlib import Path
import sys

from execution import digest
from validate5 import validate, read

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(REPO / 'week3/larb/code'))
sys.path.insert(0, str(REPO / 'week4/step1/controlled-comparison'))
from baseline import boxed  # noqa: E402
from grade_stage3 import grade_answer  # noqa: E402
from metrics import finish_kind, outcome, summarize  # noqa: E402

POLICIES = ['fixed2048', 'fixed4096', 'live', 'live_one']


def plan_short(root):
    return read(root, 'plan.json')['budget']['short']


def grade(root):
    assert metadata.version('math-verify') == '0.9.0'
    audit = validate(root)
    complete = read(root, 'run-complete.json')
    trace = read(root, 'trace.json')
    problems = read(root, 'problems100.json')
    mechanics = {r['key']: r for r in audit['rows']}
    worker = [json.loads(line) for line in (root / 'worker.jsonl').read_text().splitlines()]
    reductions = {e['key']: e for e in worker if e['event'] == 'live_reduction'}
    admitted = {e['key']: e for e in worker if e['event'] == 'admitted'}
    rows = []
    for phase in complete['phases'][1:]:
        for client in phase['client']:
            key = client['key']
            m = mechanics[key]
            raw = read(root, f'requests/{key}.json')
            post = (raw['raw_output'].split('</think>', 1)[1]
                    if '</think>' in raw['raw_output'] else '')
            extracted = boxed(post)
            g = grade_answer(str(problems[client['index']]['answer']), extracted)
            finish = finish_kind(raw, m['cap'])
            elapsed = client['client_finished'] - client['scheduled']
            cue, close, ids = m['cue_start'], m['close_index'], raw['token_ids']
            cut = reductions.get(key)
            rows.append(dict(**m, condition=audit['condition'], finish=finish, grading=g,
                extracted_answer=extracted,
                reference=str(problems[client['index']]['answer']),
                client_completion_seconds=elapsed,
                queue_seconds=admitted[key]['monotonic'] - raw['received'],
                injection_lag_ms=client['injection_lag_ms'],
                thinking_tokens=cue if cue is not None else close if close is not None else len(ids),
                cue_tokens=len(raw['cue_ids']) if cue is not None else 0,
                answer_tokens=(len(ids) - cue - len(raw['cue_ids']) if cue is not None
                               else len(ids) - close - 1 if close is not None else 0),
                seconds_cut_to_finish=(client['client_finished'] - cut['monotonic'])
                if cut and m['binding_live_cutoff'] else None,
                reduction_after_short=(cut['tokens'] - plan_short(root)) if cut else None,
                **outcome(g['correct'], finish, elapsed, trace['relative_deadline_seconds'])))
    horizon = 2 * trace['observation_horizon_seconds']
    summaries = [dict(policy=p, **summarize([r for r in rows if r['policy'] == p], horizon))
                 for p in POLICIES]
    paired = []
    for block in sorted({r['block'] for r in rows}):
        for index in sorted({r['index'] for r in rows}):
            cell = {r['policy']: r for r in rows if r['block'] == block and r['index'] == index}
            if len(cell) < len(POLICIES):
                continue
            paired.append(dict(block=block, index=index,
                on_time={p: bool(cell[p]['correct_on_time']) for p in POLICIES},
                eventual={p: bool(cell[p]['completed_correct']) for p in POLICIES},
                live_one_minus_fixed2048=int(cell['live_one']['correct_on_time'])
                - int(cell['fixed2048']['correct_on_time']),
                eventual_live_one_minus_fixed2048=int(cell['live_one']['completed_correct'])
                - int(cell['fixed2048']['completed_correct']),
                completion={p: cell[p]['client_completion_seconds'] for p in POLICIES},
                thinking={p: cell[p]['thinking_tokens'] for p in POLICIES}))
    result = dict(condition=audit['condition'], validation_passed=audit['passed'],
        coverage=audit['coverage'], measured_outcomes=len(rows),
        unique_questions=len({r['index'] for r in rows}),
        relative_deadline_seconds=trace['relative_deadline_seconds'],
        unit_seconds=trace['unit_seconds'], summary=summaries, paired=paired,
        overlap_by_phase=audit['overlap_by_phase'],
        binding_cut_to_finish_seconds=[r['seconds_cut_to_finish'] for r in rows
                                       if r['seconds_cut_to_finish'] is not None],
        reduction_after_short_tokens=[r['reduction_after_short'] for r in rows
                                      if r['reduction_after_short'] is not None],
        audit={k: v for k, v in audit.items() if k != 'rows'},
        input_hashes={n: digest(root / n) for n in ['plan.json', 'trace.json', 'manifest.json']},
        grading_versions={n: metadata.version(n) for n in
                          ['math-verify', 'sympy', 'latex2sympy2_extended']})
    out = root / 'analysis'
    out.mkdir(exist_ok=True)
    for name, value in [('summary.json', result), ('graded.json', rows),
                        ('pairs.json', paired),
                        ('review-queue.json', [r for r in rows if r['grading']['issue']
                                               or not r['completed_correct']])]:
        (out / name).write_text(json.dumps(value, indent=2) + '\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    result = grade(args.root)
    print(json.dumps(dict(summary=result['summary'], coverage=result['coverage']), indent=2))
