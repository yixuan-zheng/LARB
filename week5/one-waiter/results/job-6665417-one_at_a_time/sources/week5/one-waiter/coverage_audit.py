"""Coverage audit: expected versus achieved Week 5 answers, per condition.

Written before any Week 5 answer existed, so the expected numbers come from the
frozen plan only. Gate answers are mechanics evidence and are never counted as
measured science.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICIES = 4
BLOCKS = 2


def audit(results=HERE / 'results'):
    plan = json.loads((HERE / 'plan.json').read_text())
    expected = {name: plan['coverage'][name] * POLICIES * BLOCKS
                for name in ['constant_pressure', 'one_at_a_time', 'slack_rush_recovery']}
    planned = plan['coverage']['planned_full_design']['measured_outcomes']
    achieved, notes, gate = {}, {}, None
    for run in sorted(results.glob('job-*')):
        complete = run / 'run-complete.json'
        if not complete.exists():
            continue
        data = json.loads(complete.read_text())
        condition = data['condition']
        requests = data['measured_requests']
        if condition == 'gate':
            gate = dict(run=run.name, answers=requests, phases=data['phases'][1:] and
                        [p['phase'] for p in data['phases'][1:]])
            continue
        achieved[condition] = achieved.get(condition, 0) + requests
        if data['skipped']:
            notes[condition] = ('truncated inside the frozen wall-clock cap',
                                [s['block'] for s in data['skipped']])
    rows = []
    for condition in ['constant_pressure', 'one_at_a_time', 'slack_rush_recovery']:
        rows.append(dict(condition=condition, expected_answers=expected[condition],
                         achieved_answers=achieved.get(condition, 0),
                         note=notes.get(condition,
                                        'not run: no allocation for this condition'
                                        if not achieved.get(condition) else 'complete')))
    total_expected = sum(expected.values())
    total_achieved = sum(achieved.values())
    return dict(plan=plan['id'], planned_design_answers=planned,
                expected_with_week5_coverage=total_expected,
                achieved_measured_answers=total_achieved,
                gate_answers_excluded=gate,
                fractions=round(total_achieved / planned, 4),
                coverage_of_week5_plan=round(total_achieved / total_expected, 4),
                per_condition=rows,
                accounting='Every achieved answer has a raw request record and a graded row; '
                           'missing answers are conditions that did not run, not dropped records.')


if __name__ == '__main__':
    result = audit()
    (HERE / 'coverage-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
