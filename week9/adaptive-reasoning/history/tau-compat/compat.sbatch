#!/bin/bash
# Invoke with two 90-minute heterogeneous Slurm components.
set -euo pipefail
export TAU_OUT="$TAU_ROOT/results-${SLURM_JOB_ID}"
mkdir -m 700 "$TAU_OUT"
head -c 24 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$TAU_OUT/key"
chmod 600 "$TAU_OUT/key"
srun --het-group=1 --ntasks=1 bash "$TAU_ROOT/harness/serve.sh" customer > "$TAU_OUT/customer.log" 2>&1 &
srun --het-group=0 --ntasks=1 bash "$TAU_ROOT/harness/serve.sh" agent > "$TAU_OUT/agent.log" 2>&1 &
trap 'jobs -pr | xargs -r kill' EXIT
for i in $(seq 1 150); do
    if [[ -s "$TAU_OUT/done" ]]; then
        exit "$(cat "$TAU_OUT/done")"
    fi
    sleep 30
done
exit 1
