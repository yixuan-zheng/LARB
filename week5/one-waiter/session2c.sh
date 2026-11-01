#!/bin/bash
# Slack → rush → recovery, third start, under the real allocation label.
# The two earlier starts produced no answers: attempt5 died at engine start on an orphaned
# EngineCore, and attempt7 was launched by a watchdog that did not inherit SLURM_JOB_ID and so
# wrote into a directory labelled 6662944. Neither is a scientific record.
set -uo pipefail
cd /home/hice1/jwang3221/scratch/LARB/week5/one-waiter || exit 1
[ -e results/job-6662944-slack_rush_recovery ] &&
  mv results/job-6662944-slack_rush_recovery results/attempt7-slack_rush_recovery-wrong-allocation-label
echo "=== slack start $(date -Is)"
W5_ALLOCATION=6665417 ./launch.sh slack_rush_recovery 3300 > slack.log 2>&1
echo "=== slack exit=$? $(date -Is)"
./after.sh
