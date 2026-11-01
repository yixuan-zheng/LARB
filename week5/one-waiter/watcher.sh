#!/bin/bash
# Score each measured condition as soon as it finishes, and record the outcome.
# Runs beside session2b.sh; writes scoring.log. CPU only (analysis venv).
HERE=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter
PY=/home/hice1/jwang3221/scratch/LARB-week5-env/analysis-venv/bin/python
LOG="$HERE/scoring.log"
: > "$LOG"
for cond in one_at_a_time slack_rush_recovery; do
  run="$HERE/results/job-6665417-$cond"
  until [ -f "$run/run-complete.json" ] || [ -f "$run/run-failed.json" ]; do sleep 30; done
  if [ -f "$run/run-failed.json" ]; then
    echo "$(date -Is) $cond FAILED: $(cat "$run/run-failed.json")" >> "$LOG"
    continue
  fi
  echo "$(date -Is) scoring $cond" >> "$LOG"
  ( cd "$HERE" && "$PY" -B analyze5.py --root "$run" >> "$LOG" 2>&1 )
  echo "$(date -Is) scored $cond exit=$? -> $run/analysis/summary.json" >> "$LOG"
done
echo "$(date -Is) watcher done" >> "$LOG"
