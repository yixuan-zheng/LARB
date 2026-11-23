#!/bin/bash
#SBATCH --nodes=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=00:45:00
set -euo pipefail
cd "${BACKEND_ROOT:?}"
mkdir "job-$SLURM_JOB_ID"
cd "job-$SLURM_JOB_ID"
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$BACKEND_ROOT:$BACKEND_ROOT/repo/week7/scaled-serving/code"
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
export ADAPTER_SOURCE="$HOME/scratch/larb-grpo-screen.lG0MK92r"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn
export OPENBLAS_NUM_THREADS=1 TOKENIZERS_PARALLELISM=false
local_dir=$(mktemp -d /tmp/larb-backend.XXXXXXXX)
export LARB_OUT="$local_dir/controller"
nvidia-smi --query-gpu=timestamp,name,memory.used,memory.total,utilization.gpu --format=csv -l 5 > gpu.csv &
sampler=$!
trap 'kill "$sampler" 2>/dev/null || true; rm -rf "$local_dir"' EXIT
timeout --kill-after=15s 40m "$base/vllm-proof-env/bin/python" -u "$BACKEND_ROOT/gate.py"
