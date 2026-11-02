"""Freeze the Week 5 source lock; run after the last source edit, before inference."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ONE_WAITER = HERE.parent
CONFIG = ONE_WAITER / 'config'
REPO = HERE.parents[3]
FILES = [
    'week5/builder/one-waiter/code/bootstrap.py',
    'week5/builder/one-waiter/code/cohort.py',
    'week5/builder/one-waiter/config/cohort.json',
    'week5/builder/one-waiter/code/execution.py',
    'week5/builder/one-waiter/code/genplan.py',
    'week5/builder/one-waiter/code/coverage_audit.py',
    'week5/builder/one-waiter/code/preflight.py',
    'week5/builder/one-waiter/code/run_condition.sbatch',
    'week5/builder/one-waiter/config/plan.json',
    'week5/builder/one-waiter/code/launch.sh',
    'week5/builder/one-waiter/code/run_week5.py',
    'week5/builder/one-waiter/code/summarize_results.py',
    'week5/builder/one-waiter/code/test_policy.py',
    'week5/builder/one-waiter/code/validate5.py',
    'week5/builder/one-waiter/code/analyze5.py',
    'week5/builder/one-waiter/code/w5_adapter.py',
    'week5/builder/one-waiter/code/w5_policy.py',
    'week5/builder/one-waiter/code/w5_server.py',
    'week5/builder/one-waiter/inputs/problems100.json',
    'week5/builder/one-waiter/inputs/dataset-manifest.json',
    'week3/larb/burst-policy/adapter.py',
    'week3/larb/burst-policy/policy.py',
    'week3/larb/serving-proof/control.py',
    'week3/larb/code/baseline.py',
    'week3/larb/code/grade_stage3.py',
    'week4/baseline-controls/w4_policy.py',
    'week4/step1/controlled-comparison/metrics.py',
]
lock = {name: hashlib.sha256((REPO / name).read_bytes()).hexdigest() for name in FILES}
CONFIG.mkdir(exist_ok=True)
(CONFIG / 'source-lock.json').write_text(json.dumps(lock, indent=2) + '\n')
print('locked', len(lock), 'files')
print('week4 controller unchanged:',
      lock['week4/baseline-controls/w4_policy.py'] ==
      json.loads((REPO / 'week4/baseline-controls/source-lock.json').read_text())[
          'week4/baseline-controls/w4_policy.py'])
