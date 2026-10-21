#!/bin/bash
#SBATCH --job-name=qwen3-sweetspot
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --array=0-29%6
set -euo pipefail
source "${PACE_ENV_ROOT:?Set PACE_ENV_ROOT}/gemma3n/bin/activate"
export HF_HOME="${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
python -u code/stage3_sweep.py --task "$SLURM_ARRAY_TASK_ID"
