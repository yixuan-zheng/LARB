#!/bin/bash
# Wait for both session-2 conditions, then score and dump report numbers. CPU only.
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONE_WAITER="$(dirname "$CODE")"
until [ -f "$ONE_WAITER/results/job-6665417-one_at_a_time/run-complete.json" ]; do sleep 20; done
"$CODE/after.sh"
until [ -f "$ONE_WAITER/results/job-6665417-slack_rush_recovery/run-complete.json" ] \
   || [ -f "$ONE_WAITER/results/job-6665417-slack_rush_recovery/run-failed.json" ]; do sleep 20; done
"$CODE/after.sh"
echo "autofinish done $(date -Is)" >> "$ONE_WAITER/logs/scoring.log"
