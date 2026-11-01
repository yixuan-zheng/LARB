#!/bin/bash
# Session 2 chain: gate, then one_at_a_time, then slack_rush_recovery, in one 4-hour
# interactive H100 allocation. Each condition is its own process and output directory.
# The measured-phase cap of each condition is fixed from the remaining wall clock at
# the moment it starts, so a short session truncates later phases instead of losing
# the run. No retries.
set -uo pipefail
HERE=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter
export W5_ALLOCATION=${SLURM_JOB_ID:?need SLURM_JOB_ID}
END=$(date -d "$(scontrol show job "$W5_ALLOCATION" | grep -oP 'EndTime=\S+' | head -1 | cut -d= -f2)" +%s)
remaining() { echo $(( END - $(date +%s) - 240 )); }
run() {
  local cond=$1 cap=$2
  echo "=== $cond cap=${cap}s start=$(date -Is) remaining=$(( END - $(date +%s) ))s"
  "$HERE/launch.sh" "$cond" "$cap"
  echo "=== $cond exit=$? end=$(date -Is) remaining=$(( END - $(date +%s) ))s"
}
run gate 800
[ -f "$HERE/results/job-$W5_ALLOCATION-gate/mechanical-validation.json" ] &&
  grep -q '"passed": true' "$HERE/results/job-$W5_ALLOCATION-gate/mechanical-validation.json" ||
  echo "=== gate did not pass; continuing only because conditions are independent"
run one_at_a_time 6600
CAP=$(remaining)
if [ "$CAP" -gt 600 ]; then run slack_rush_recovery "$CAP"; else echo "=== skip slack_rush_recovery: ${CAP}s left"; fi
echo "=== chain done $(date -Is)"
