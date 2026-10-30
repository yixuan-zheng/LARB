"""Freeze the Week 5 source lock; run after the last source edit, before inference."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
FILES = [
    'week5/one-waiter/bootstrap.py',
    'week5/one-waiter/cohort.py',
    'week5/one-waiter/cohort.json',
    'week5/one-waiter/execution.py',
    'week5/one-waiter/genplan.py',
    'week5/one-waiter/coverage_audit.py',
    'week5/one-waiter/preflight.py',
    'week5/one-waiter/run_condition.sbatch',
    'week5/one-waiter/plan.json',
    'week5/one-waiter/launch.sh',
    'week5/one-waiter/run_week5.py',
    'week5/one-waiter/summarize_results.py',
    'week5/one-waiter/test_policy.py',
    'week5/one-waiter/validate5.py',
    'week5/one-waiter/analyze5.py',
    'week5/one-waiter/w5_adapter.py',
    'week5/one-waiter/w5_policy.py',
    'week5/one-waiter/w5_server.py',
    'week5/one-waiter/inputs/problems100.json',
    'week5/one-waiter/inputs/dataset-manifest.json',
    'week3/larb/burst-policy/adapter.py',
    'week3/larb/burst-policy/policy.py',
    'week3/larb/serving-proof/control.py',
    'week3/larb/code/baseline.py',
    'week3/larb/code/grade_stage3.py',
    'week4/baseline-controls/w4_policy.py',
    'week4/step1/controlled-comparison/metrics.py',
]
lock = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in FILES}
(HERE / 'source-lock.json').write_text(json.dumps(lock, indent=2) + '\n')
print('locked', len(lock), 'files')
print('week4 controller unchanged:',
      lock['week4/baseline-controls/w4_policy.py'] ==
      json.loads((REPO / 'week4/baseline-controls/source-lock.json').read_text())[
          'week4/baseline-controls/w4_policy.py'])
