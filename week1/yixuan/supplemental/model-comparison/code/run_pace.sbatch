#!/bin/bash
#SBATCH --job-name=model-decision
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=48G
#SBATCH --time=00:45:00
set -euo pipefail
: "${DECISION_ROOT:?Set DECISION_ROOT to the uploaded model-decision folder}"
: "${GEMMA_ROOT:?Set GEMMA_ROOT to the existing Gemma setup}"
: "${NANOCHAT_ROOT:?Set NANOCHAT_ROOT to the existing Nanochat setup}"
source "$GEMMA_ROOT/gemma3n/bin/activate"
export PYTHONPATH="$NANOCHAT_ROOT/deps:$NANOCHAT_ROOT/code"
export HF_HUB_OFFLINE=1
export HF_HOME="$NANOCHAT_ROOT/hf-cache"
python -u "$DECISION_ROOT/code/decision_check.py" --model nanochat --output "$DECISION_ROOT/results/nanochat.json"
export HF_HOME="$GEMMA_ROOT/hf-cache"
python -u "$DECISION_ROOT/code/decision_check.py" --model gemma --output "$DECISION_ROOT/results/gemma.json"
