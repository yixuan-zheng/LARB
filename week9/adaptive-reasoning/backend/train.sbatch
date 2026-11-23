#!/bin/bash
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
set -euo pipefail
cd "${BACKEND_ROOT:?}"
sha256sum -c followup.sha256
mkdir "train-$SLURM_JOB_ID"
cd "train-$SLURM_JOB_ID"
ln -s "$BACKEND_ROOT/mixed-freeze.json" freeze.json
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$BACKEND_ROOT:$BACKEND_ROOT/repo/week7/scaled-serving/code"
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
start=$(date +%s)
export EVAL_END_EPOCH=$(( start + LARB_WALL_MIN * 60 - 300 ))
if (( EVAL_END_EPOCH > LARB_CUTOFF_EPOCH )); then export EVAL_END_EPOCH="$LARB_CUTOFF_EPOCH"; fi
export TRAIN_END_EPOCH=$((EVAL_END_EPOCH - LARB_EVAL_MIN*60))
if (( TRAIN_END_EPOCH-start < LARB_TRAIN_MIN*60 )); then
    echo "Queue start leaves insufficient time for training and reserved held-out evaluation." >&2
    exit 1
fi
local_dir=$(mktemp -d /tmp/larb-followup.XXXXXXXX)
export LARB_OUT="$local_dir/controller"
nvidia-smi --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu --format=csv -l 15 > gpu.csv &
sampler=$!
py="$base/vllm-proof-env/bin/python"
finish() {
    status=$?
    kill "$sampler" 2>/dev/null || true
    "$py" "$BACKEND_ROOT/score_mixed.py" || true
    rm -rf "$local_dir"
    exit "$status"
}
trap finish EXIT
timeout --kill-after=10s "$((EVAL_END_EPOCH-start))s" "$py" -u "$BACKEND_ROOT/followup.py"
