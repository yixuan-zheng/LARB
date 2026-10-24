#!/bin/bash
#SBATCH --job-name=larb-fixed-cpu
#SBATCH --account=coc
#SBATCH --partition=coc-cpu
#SBATCH --qos=coc-ice
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:20:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?}"
source vllm-proof-env/bin/activate
export LARB_WEEK3_ROOT="$PWD"
export PYTHONPATH="$PWD/week4/reserved-validation/.analysis-deps:$PWD/week4/baseline-controls:$PWD/burst-policy:$PWD/serving-proof"
python -B week4/baseline-controls/preflight.py
python -B -m unittest discover -s week4/baseline-controls -p 'test_*.py'
python -B - <<'PY'
from pathlib import Path
import sys
sys.path[:0]=['week3/larb/code','week4/step1/controlled-comparison']
from baseline import boxed
from grade_stage3 import grade_answer
from metrics import outcome
import json
root=Path('week4/reserved-validation/results/job-6481923')
problems=json.loads((root/'problems100.json').read_text())
saved=json.loads((root/'analysis/graded.json').read_text())[0]
raw=json.loads((root/'requests'/(saved['key']+'.json')).read_text())
g=grade_answer(str(problems[raw['index']]['answer']),boxed(raw['raw_output'].split('</think>',1)[1]))
assert g['correct']==saved['grading']['correct']
print('PASS: saved real-result scoring fixture')
PY
