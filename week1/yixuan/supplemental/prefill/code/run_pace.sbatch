#!/bin/bash
#SBATCH --job-name=prefill-overload
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=01:00:00
set -euo pipefail
: "${EXPERIMENT_ROOT:?}" "${GEMMA_ROOT:?}"
source "$GEMMA_ROOT/gemma3n/bin/activate"
export HF_HOME="$GEMMA_ROOT/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
python -u "$EXPERIMENT_ROOT/code/run_experiment.py" --root "$EXPERIMENT_ROOT"
