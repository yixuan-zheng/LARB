#!/bin/bash
#SBATCH --job-name=qwen3-baseline
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=00:45:00
set -euo pipefail
source "${PACE_ENV_ROOT:?Set PACE_ENV_ROOT}/gemma3n/bin/activate"
export HF_HOME="${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}/hf-cache"
export PYTHONPATH="${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}/deps${PYTHONPATH:+:$PYTHONPATH}"
export TOKENIZERS_PARALLELISM=false
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
nvidia-smi
python -u code/baseline.py --out "results/job-$SLURM_JOB_ID"
