#!/bin/bash
# Score each measured condition as soon as it finishes, and record the outcome.
# Runs beside session2b.sh; writes logs/scoring.log. CPU only (analysis venv).
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONE_WAITER="$(dirname "$CODE")"
REPO="$(cd "$ONE_WAITER/../../.." && pwd)"
ENV_ROOT="${LARB_W5_ENV_ROOT:-$REPO/.w5-env}"
PY="${LARB_W5_ANALYSIS_PYTHON:-$ENV_ROOT/analysis-venv/bin/python}"
LOG="$ONE_WAITER/logs/scoring.log"
: > "$LOG"
for cond in one_at_a_time slack_rush_recovery; do
  run="$ONE_WAITER/results/job-6665417-$cond"
  until [ -f "$run/run-complete.json" ] || [ -f "$run/run-failed.json" ]; do sleep 30; done
  if [ -f "$run/run-failed.json" ]; then
    echo "$(date -Is) $cond FAILED: $(cat "$run/run-failed.json")" >> "$LOG"
    continue
  fi
  echo "$(date -Is) scoring $cond" >> "$LOG"
  ( cd "$ONE_WAITER" && "$PY" -B "$CODE/analyze5.py" --root "$run" >> "$LOG" 2>&1 )
  echo "$(date -Is) scored $cond exit=$? -> $run/analysis/summary.json" >> "$LOG"
done
echo "$(date -Is) watcher done" >> "$LOG"
