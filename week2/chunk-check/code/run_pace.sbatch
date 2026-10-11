#!/bin/bash
#SBATCH --job-name=chunk-check
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:30:00
set -euo pipefail
source "$HOME/scratch/CS6222-matformer-local-test/gemma3n/bin/activate"
export HF_HOME="$HOME/scratch/CS6222-matformer-local-test/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
cd "$FINAL_ROOT"
mkdir -p week2/chunk-check/results
nvidia-smi
python -u week2/chunk-check/code/run_check.py --out "week2/chunk-check/results/job-${SLURM_JOB_ID}.json"
