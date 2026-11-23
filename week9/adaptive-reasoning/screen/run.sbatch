#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=07:00:00
set -euo pipefail
cd "${SCREEN_ROOT:?}"
sha256sum -c input.sha256
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$PWD:$PWD/repo/week7/scaled-serving/code"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false OPENBLAS_NUM_THREADS=1
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
start=$(date +%s)
export EVAL_END_EPOCH=$((start + 6*3600 + 45*60))
if (( EVAL_END_EPOCH > CUTOFF_EPOCH )); then export EVAL_END_EPOCH="$CUTOFF_EPOCH"; fi
export TRAIN_END_EPOCH=$((EVAL_END_EPOCH - 3*3600 - 30*60))
if (( TRAIN_END_EPOCH < start + 45*60 )); then
    echo "Insufficient time before cutoff for training and reserved evaluation." >&2
    exit 1
fi
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 15 > gpu.csv &
sampler=$!
py="$base/vllm-proof-env/bin/python"
finish() {
    status=$?
    kill "$sampler" 2>/dev/null || true
    "$py" score.py || true
    exit "$status"
}
trap finish EXIT
timeout --kill-after=15s "$((EVAL_END_EPOCH-start))s" "$py" -u screen.py
