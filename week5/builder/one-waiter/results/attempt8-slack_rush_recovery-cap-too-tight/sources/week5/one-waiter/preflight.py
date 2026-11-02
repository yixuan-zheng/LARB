"""CPU preflight: catch plan/input/key bugs before an H100 allocation is spent.

Run this before any GPU launch. It verified nothing about the model; it exists
because three GPU attempts were lost to key-name and input sparsity bugs that a
two-second CPU check would have caught.
"""
import argparse
import hashlib
import importlib.metadata as metadata
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
from execution import digest, trace_for  # noqa: E402
import cohort  # noqa: E402


def check_lock():
    lock = json.loads((HERE / 'source-lock.json').read_text())
    for name, expected in lock.items():
        path = REPO / name
        assert path.exists(), 'locked file missing: ' + name
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected, 'lock mismatch: ' + name
    week4 = json.loads((REPO / 'week4/baseline-controls/source-lock.json').read_text())
    assert lock['week4/baseline-controls/w4_policy.py'] == week4['week4/baseline-controls/w4_policy.py'], \
        'Week 4 controller was modified'
    for name in ['week3/larb/burst-policy/adapter.py', 'week3/larb/serving-proof/control.py']:
        assert name in lock
    return len(lock)


def check_plan_and_inputs():
    plan = json.loads((HERE / 'plan.json').read_text())
    assert plan['cohort']['rank_order'] == cohort.cohort(), 'cohort does not match the published rule'
    assert not set(plan['cohort']['rank_order']) & set(cohort.USED), 'cohort reuses used indices'
    problems = json.loads((HERE / 'inputs/problems100.json').read_text())
    offsets = plan['coverage']['cohort_offset']
    slices = {}
    for condition in ['constant_pressure', 'one_at_a_time', 'slack_rush_recovery']:
        start, count = offsets[condition], plan['coverage'][condition]
        slices[condition] = plan['cohort']['rank_order'][start:start + count]
        assert len(slices[condition]) == count, f'{condition}: slice exceeds the rank order'
    spent = [i for ids in slices.values() for i in ids]
    assert len(spent) == len(set(spent)), 'condition cohort slices overlap'
    enrolled = set(plan['calibration']['indices']) | set(plan['gate']['indices'])
    enrolled |= set(spent)
    missing = sorted(i for i in enrolled if i >= len(problems) or problems[i] is None)
    assert not missing, f'inputs/problems100.json lacks enrolled indices {missing}'
    for i in enrolled:
        assert problems[i]['problem'] and str(problems[i]['answer']), 'incomplete row ' + str(i)
    return plan, sorted(enrolled)


def check_traces(plan):
    calibration = dict(client=[dict(status='terminal', client_finished=100.0, scheduled=0.0),
                               dict(status='terminal', client_finished=95.0, scheduled=0.0)])
    shapes = {}
    for condition in ['gate', 'one_at_a_time', 'constant_pressure', 'slack_rush_recovery']:
        trace = trace_for(plan, condition, calibration, 1.0)
        count = len(trace['arrivals_by_block'][0])
        assert count != 0 or condition == 'slack_rush_recovery', f'{condition} built an empty trace'
        for block in trace['block_order']:
            assert block in trace['orders'], f'missing order for block {block}'
            assert len(trace['orders'][block]) == 4 or condition == 'gate', 'measured order incomplete'
        assert trace['relative_deadline_seconds'] > 0
        shapes[condition] = dict(per_block=count, blocks=len(trace['block_order']),
                                 orders=trace['orders'],
                                 offsets=[round(a['offset_seconds'], 1)
                                          for a in trace['arrivals_by_block'][0]])
    return shapes


def check_runtime(model_path=None):
    plan = json.loads((HERE / 'plan.json').read_text())
    versions = {}
    for name in ['vllm', 'torch', 'transformers']:
        versions[name] = metadata.version(name)
        assert versions[name].split('+')[0] == plan['engine'][name], \
            f'{name} {versions[name]} != plan {plan["engine"][name]}'
    if model_path:
        model = Path(model_path)
        index = json.loads((model / 'model.safetensors.index.json').read_text())
        for shard in sorted(set(index['weight_map'].values())):
            assert (model / shard).stat().st_size > 0, 'missing shard ' + shard
        return versions, index['metadata']['total_size']
    return versions, None


def check_unit_tests():
    result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', str(HERE),
                             '-p', 'test_*.py'], capture_output=True, text=True)
    assert result.returncode == 0, 'unit tests failed:\n' + result.stderr[-2000:]
    return result.stderr.strip().splitlines()[-1]


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--local', action='store_true', help='skip runtime/model checks')
    parser.add_argument('--model-path', default=None)
    args = parser.parse_args()
    report = dict(locked_files=check_lock(), unit_tests=check_unit_tests())
    report['plan'], report['enrolled_indices'] = check_plan_and_inputs()
    report['plan'] = report['plan']['id']
    report['trace_shapes'] = check_traces(json.loads((HERE / 'plan.json').read_text()))
    if not args.local:
        report['runtime_versions'], report['model_parameter_bytes'] = check_runtime(args.model_path)
    print(json.dumps(report, indent=2))
    print('PASS: locks, tests, plan keys, cohort, inputs, traces' +
          ('' if args.local else ', runtime and model files'))
