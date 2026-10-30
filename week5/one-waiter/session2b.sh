#!/bin/bash
# Session 2 chain, second attempt: one_at_a_time, then slack_rush_recovery, in the same
# 4-hour interactive H100 allocation. The first attempt (see results/attempt4 and
# attempt5) died at engine start because the previous condition's EngineCore survived
# the launcher's pkill and kept 65.6 GB: this wrapper hard-kills anything still holding
# GPU memory and refuses to start a condition until the device is clean.
set -uo pipefail
HERE=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter
export W5_ALLOCATION=${SLURM_JOB_ID:?need SLURM_JOB_ID}
END=$(date -d "$(scontrol show job "$W5_ALLOCATION" | grep -oP 'EndTime=\S+' | head -1 | cut -d= -f2)" +%s)
remaining() { echo $(( END - $(date +%s) - 240 )); }

clean_gpu() {
  pkill -9 -f 'VLLM::EngineCore' 2>/dev/null
  for pid in $(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null); do
    kill -9 "$pid" 2>/dev/null
  done
  for _ in $(seq 1 60); do
    used=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)
    if [ "$used" -lt 2048 ]; then echo "gpu clean: ${used} MiB used"; return 0; fi
    sleep 2
  done
  echo "ABORT: GPU still holds ${used} MiB after cleanup" >&2
  return 1
}

run() {
  local cond=$1 cap=$2
  clean_gpu || return 1
  echo "=== $cond cap=${cap}s start=$(date -Is) remaining=$(( END - $(date +%s) ))s"
  "$HERE/launch.sh" "$cond" "$cap"
  echo "=== $cond exit=$? end=$(date -Is) remaining=$(( END - $(date +%s) ))s"
}

run one_at_a_time 6000
CAP=$(remaining)
if [ "$CAP" -gt 900 ]; then run slack_rush_recovery "$CAP"; else echo "=== skip slack_rush_recovery: ${CAP}s left"; fi
clean_gpu
echo "=== chain done $(date -Is)"
