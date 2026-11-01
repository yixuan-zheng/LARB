#!/bin/bash
# Wait for both session-2 conditions, then score and dump report numbers. CPU only.
HERE=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter
until [ -f "$HERE/results/job-6665417-one_at_a_time/run-complete.json" ]; do sleep 20; done
"$HERE/after.sh"
until [ -f "$HERE/results/job-6665417-slack_rush_recovery/run-complete.json" ] \
   || [ -f "$HERE/results/job-6665417-slack_rush_recovery/run-failed.json" ]; do sleep 20; done
"$HERE/after.sh"
echo "autofinish done $(date -Is)" >> "$HERE/scoring.log"
