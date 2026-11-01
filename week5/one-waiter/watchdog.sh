#!/bin/bash
# Let one_at_a_time finish, then cap slack_rush_recovery to what the evening can hold:
# four measured phases (block 0) plus the 1.2x margin the runner needs, instead of the
# ~5,600 s the chain would otherwise take. No answer exists when this decision is made;
# it is a wall-clock cap, not a selection of outcomes.
set -uo pipefail
cd /home/hice1/jwang3221/scratch/LARB/week5/one-waiter || exit 1
LOG=watchdog.log
OUT=results/job-6665417-slack_rush_recovery
until [ -f results/job-6665417-one_at_a_time/run-complete.json ]; do sleep 10; done
sleep 4
pkill -f 'session2b.sh' 2>/dev/null
pkill -f 'launch.sh slack_rush_recovery' 2>/dev/null
pkill -f 'condition slack_rush_recovery' 2>/dev/null
pkill -f 'w5_server.py' 2>/dev/null
for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do kill -9 "$pid" 2>/dev/null; done
if [ -e "$OUT" ]; then mv "$OUT" "results/attempt6-6665417-slack_rush_recovery-recap-before-cap"; fi
echo "$(date -Is) starting slack with cap 3400s" >> "$LOG"
./launch.sh slack_rush_recovery 3400 >> "$LOG" 2>&1
echo "$(date -Is) slack exit=$?" >> "$LOG"
