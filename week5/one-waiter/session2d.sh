#!/bin/bash
# Fourth start of slack_rush_recovery. The 3,300 s cap was too tight: the runner reserves
# 1.2x the worst completed phase before starting another one, and four phases are needed for
# all four policies to appear at all. 4,200 s guarantees block 0 and still ends inside the
# allocation. No answer exists from the earlier starts.
set -uo pipefail
cd /home/hice1/jwang3221/scratch/LARB/week5/one-waiter || exit 1
for pid in $(ps -o pid,cmd -u "$USER" | awk '/run_week5.py --condition slack_rush_recovery|w5_server.py/ && !/awk/ {print $1}'); do
  kill -TERM "$pid" 2>/dev/null
done
sleep 5
for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do kill -9 "$pid" 2>/dev/null; done
sleep 4
used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
[ "$used" -lt 2048 ] || { echo "ABORT: GPU holds ${used} MiB"; exit 1; }
[ -e results/job-6665417-slack_rush_recovery ] &&
  mv results/job-6665417-slack_rush_recovery results/attempt8-slack_rush_recovery-cap-too-tight
echo "=== slack 4th start $(date -Is) gpu=${used}MiB"
W5_ALLOCATION=6665417 ./launch.sh slack_rush_recovery 4200 > slack.log 2>&1
echo "=== slack exit=$? $(date -Is)"
./after.sh
