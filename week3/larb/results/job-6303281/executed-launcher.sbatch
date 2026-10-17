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
source "$HOME/scratch/CS6222-matformer-local-test/gemma3n/bin/activate"
export HF_HOME="$HOME/scratch/CS6222-qwen3-baseline/hf-cache"
export PYTHONPATH="$HOME/scratch/CS6222-qwen3-baseline/deps${PYTHONPATH:+:$PYTHONPATH}"
export TOKENIZERS_PARALLELISM=false
cd "$HOME/scratch/CS6222-qwen3-baseline"
nvidia-smi
python -u code/baseline.py --out "results/job-$SLURM_JOB_ID"
