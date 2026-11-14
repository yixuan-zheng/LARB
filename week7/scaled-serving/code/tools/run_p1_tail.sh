#!/bin/bash
# P1 tail driver: finish Gate C, then run Gates D, E and F in order.
# Usage: run_p1_tail.sh <sweep-pid>
set -uo pipefail

ROOT=${LARB_ROOT:-/home/hice1/jwang3221/scratch/LARB}
PY=${LARB_PYTHON:-/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python}
APY=${LARB_ANALYSIS_PYTHON:-/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python}
RESULTS="$ROOT/week7/scaled-serving/results/p1"
LOGS="$RESULTS/logs"
export PYTHONPATH="$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:-/storage/ice1/3/0/jwang3221/LARB-week5-env/model/Qwen3-4B}
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
mkdir -p "$LOGS"

note() { echo "$(date '+%H:%M:%S') $*" >> "$LOGS/tail-driver.log"; }
cleanup() {
  "$PY" -c "import sys; sys.path.insert(0, '$ROOT/week7/scaled-serving/code'); \
from larb_scaled.runner import kill_orphan_engines; kill_orphan_engines()" >> "$LOGS/tail-driver.log" 2>&1
}
fail() { note "FAILED: $*"; exit 1; }

summarize() {
  PYTHONPATH="$PYTHONPATH" "$APY" "$ROOT/week7/scaled-serving/code/tools/summarize_gates.py" \
    --runs "$RESULTS/runs" --sweep "$RESULTS/sweep" --calibration "$RESULTS/calibration" \
    --out "$RESULTS/gates.json" >> "$LOGS/summarize.log" 2>&1
}

note "waiting for sweep pid $1"
while kill -0 "$1" 2>/dev/null; do sleep 5; done
note "sweep finished"
cleanup

note "gate C: 8k points at 16/24/32"
"$PY" -u "$ROOT/week7/scaled-serving/code/tools/throughput_sweep.py" \
  --out "$RESULTS/sweep" --concurrency 16 24 32 --thinking 8192 --seconds 300 \
  --eager --append >> "$LOGS/sweep8k.log" 2>&1 || fail "8k sweep"
cleanup

note "gate D: answer contract"
"$PY" -u -m larb_scaled.runner --stage p1-gates --only contract \
  --out "$RESULTS/runs/contract" >> "$LOGS/contract.log" 2>&1 || fail "contract"
cleanup
summarize || fail "summarize after contract"
CONTRACT=$("$PY" -c "import json; d=json.load(open('$RESULTS/gates.json')); print((d['gates'].get('contract') or {}).get('selected') or 'legacy')")
note "contract selected: $CONTRACT"

if [ "$CONTRACT" = "short_boxed" ]; then
  note "gate D follow-up: forced mechanics under the short contract"
  "$PY" -u -m larb_scaled.runner --stage p1-gates --only mechanics-forced \
    --gate-contract short_boxed --out "$RESULTS/runs/mechanics-short" \
    >> "$LOGS/mechanics-short.log" 2>&1 || fail "short mechanics"
  cleanup
fi

note "gate E: slope screen under $CONTRACT"
"$PY" -u -m larb_scaled.runner --stage p1-gates --only slope --gate-contract "$CONTRACT" \
  --out "$RESULTS/runs/slope" >> "$LOGS/slope.log" 2>&1 || fail "slope"
cleanup

note "gate F: calibration rates"
"$PY" -u "$ROOT/week7/scaled-serving/code/tools/calibrate_load.py" --stage rates \
  --out "$RESULTS/calibration" --minutes 20 >> "$LOGS/calibration-rates.log" 2>&1 || fail "calibration rates"
cleanup
"$PY" "$ROOT/week7/scaled-serving/code/tools/calibrate_load.py" --stage summarize \
  --out "$RESULTS/calibration" >> "$LOGS/calibration-summary.log" 2>&1 || fail "calibration summary"
RATE=$("$PY" -c "import json; d=json.load(open('$RESULTS/calibration/calibration.json')); print(d.get('chosen_rate_per_hour') or '')")
note "calibrated rate: ${RATE:-none}"

if [ -n "$RATE" ]; then
  note "gate F: live manipulation check at $RATE/h"
  "$PY" -u "$ROOT/week7/scaled-serving/code/tools/calibrate_load.py" --stage live \
    --out "$RESULTS/calibration" --rate "$RATE" --live-minutes 30 \
    >> "$LOGS/calibration-live.log" 2>&1 || fail "live check"
  cleanup
  "$PY" "$ROOT/week7/scaled-serving/code/tools/calibrate_load.py" --stage summarize \
    --out "$RESULTS/calibration" >> "$LOGS/calibration-summary.log" 2>&1 || fail "final calibration summary"
fi

summarize || fail "final summarize"
note "DONE"
