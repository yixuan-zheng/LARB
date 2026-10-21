#!/bin/bash
#SBATCH --job-name=qwen3-interrupt
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=00:20:00
set -euo pipefail
source "${PACE_ENV_ROOT:?Set PACE_ENV_ROOT}/gemma3n/bin/activate"
export HF_HOME="${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
python -u code/interrupt_probe.py --budget 512 --answer-cap 2048 --out "results/stage2-job-$SLURM_JOB_ID"
