#!/bin/bash
#SBATCH --job-name=qwen3-cue
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=00:10:00
set -euo pipefail
source "$HOME/scratch/CS6222-matformer-local-test/gemma3n/bin/activate"
export HF_HOME="$HOME/scratch/CS6222-qwen3-baseline/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
cd "$HOME/scratch/CS6222-qwen3-baseline"
python -u code/interrupt_probe.py --budget 512 --answer-cap 2048 --transition cue --indices 0,1,9 --out "results/stage2cue-job-$SLURM_JOB_ID"
