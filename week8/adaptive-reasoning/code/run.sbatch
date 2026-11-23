#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=00:30:00
set -euo pipefail
cd "${SLURM_SUBMIT_DIR:?}/week8/adaptive-reasoning/code"
export LARB_MODE_FIXTURE=1 LARB_BINDING_FIXTURE="${LARB_BINDING_FIXTURE:-1}"
base="$HOME/scratch/CS6222-qwen3-baseline"
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
export PYTHONPATH="$PWD:$SLURM_SUBMIT_DIR/week7/scaled-serving/code" OPENBLAS_NUM_THREADS=1
scratch=$(mktemp -d /tmp/larb-adaptive.XXXXXXXX)
export LARB_OUT="$scratch/controller"
archive="${LARB_EVIDENCE_ROOT:-$HOME/scratch}/larb-adaptive-evidence-$SLURM_JOB_ID"
mkdir "$archive"
cp probe.py train_check.py binding_processor.py "$scratch/"
cd "$scratch"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 3 > gpu.csv &
sampler=$!
cleanup() {
    kill "$sampler" 2>/dev/null || true
    cp -a "$scratch/." "$archive/" && rm -rf "$scratch"
}
trap cleanup EXIT
py="$base/vllm-proof-env/bin/python"
timeout --kill-after=15s 94m "$py" -u probe.py
timeout --kill-after=15s 18m "$py" -u train_check.py
