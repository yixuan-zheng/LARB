#!/bin/bash
# Rebuild every CPU-side Week 8 artifact and run both transition checks.
# Usage: bash week8/scaled-serving/code/tools/run_cpu_all.sh
set -euo pipefail

ROOT=${LARB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)}
WEEK8=${LARB_WEEK8_ROOT:-$ROOT/week8/scaled-serving}
PY=${LARB_PYTHON:-python3}
APY=${LARB_ANALYSIS_PYTHON:-python3}
export PYTHONPATH="$WEEK8/code:$ROOT/week7/scaled-serving/code"

cd "$ROOT"
echo "== pool =="
"$PY" "$WEEK8/code/tools/build_omni_pool.py"
echo "== traces =="
"$PY" "$WEEK8/code/tools/build_traces.py" --stage all
echo "== P1 audit =="
"$APY" "$WEEK8/code/tools/audit_p1_screen.py"
echo "== pre-calibration =="
"$PY" -m larb_week8.precalibrate
echo "== unit tests (analysis venv) =="
"$APY" -m unittest discover -s "$WEEK8/code/tests" -p 'test_*.py'
echo "== transition: analysis environment =="
"$APY" -m larb_week8.transition --skip-context \
  --out "$WEEK8/results/transition-analysis.json"
echo "== transition: serving environment =="
"$PY" -m larb_week8.transition --skip-grading --no-lock \
  --out "$WEEK8/results/transition-serving.json"
echo "== done =="
