#!/bin/bash
#SBATCH --job-name=larb-w5
#SBATCH --account=coc
#SBATCH --partition=ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=04:00:00
# One Week 5 condition per job. Submit as:
#   CONDITION=constant_pressure CAP_SECONDS=3300 sbatch --export=ALL week5/one-waiter/run_condition.sbatch
# `--mem=64G` matters: the earlier 16G allocation was OOM-killed while vLLM loaded.
set -uo pipefail
cd /home/hice1/jwang3221/scratch/LARB
W5_ALLOCATION="$SLURM_JOB_ID" exec week5/one-waiter/launch.sh "${CONDITION:?}" "${CAP_SECONDS:?}"
