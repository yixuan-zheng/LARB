#!/bin/bash
#SBATCH --partition=ice-cpu
#SBATCH --cpus-per-task=1
#SBATCH --mem=1G
#SBATCH --time=00:10:00
set -euo pipefail
cd "${BACKEND_ROOT:?}"
sha256sum -c followup.sha256
if [[ ${1:-} == fallback ]]; then
    export LARB_FALLBACK_NOW=1
elif [[ -n ${1:-} ]]; then
    # Slurm accounting can briefly lag the dependency release.
    for attempt in 1 2 3 4; do
        state=$(sacct -n -X -j "$1" -o State -P)
        case "$state" in
            ""|PENDING|RUNNING|CONFIGURING|COMPLETING) sleep 5 ;;
            *) break ;;
        esac
    done
fi
flock selection.lock bash -c 'test -e selected-training.json || python3 choose_training.py'
