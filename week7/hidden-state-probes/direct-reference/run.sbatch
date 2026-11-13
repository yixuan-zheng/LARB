#!/bin/bash
#SBATCH -A coc
#SBATCH -p coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH -c 8
#SBATCH --mem=48G
#SBATCH -t 01:00:00
#SBATCH -J larb-hidden-state
set -euo pipefail
cd "${1:?release}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=4 TOKENIZERS_PARALLELISM=false
srun --kill-on-bad-exit=1 "${2:?python}" -B -u extract.py "${3:?model}" "${4:?output}/job-${SLURM_JOB_ID:?}"
