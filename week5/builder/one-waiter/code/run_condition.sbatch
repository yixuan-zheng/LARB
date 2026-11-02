#!/bin/bash
#SBATCH --job-name=larb-w5
#SBATCH --account=coc
#SBATCH --partition=ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
# One Week 5 condition per job. Submit from anywhere as:
#   CONDITION=constant_pressure CAP_SECONDS=3300 sbatch --export=ALL week5/builder/one-waiter/code/run_condition.sbatch
# `--mem=64G` matters: the earlier 16G allocation was OOM-killed while vLLM loaded.
set -uo pipefail
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$CODE/../../../.." && pwd)"
cd "$REPO"
W5_ALLOCATION="$SLURM_JOB_ID" exec "$CODE/launch.sh" "${CONDITION:?}" "${CAP_SECONDS:?}"
