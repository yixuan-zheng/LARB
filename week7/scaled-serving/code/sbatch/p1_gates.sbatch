#!/bin/bash
# P1 gate job draft. This script does not submit itself.
#SBATCH --job-name=larb-p1-gates
#SBATCH --partition=ice-gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=08:00:00
set -uo pipefail

ROOT=${LARB_ROOT:?set LARB_ROOT to the repository root}
PY=${LARB_PYTHON:?set LARB_PYTHON to the serving venv python}
OUT=${LARB_OUT:?set LARB_OUT to a run directory outside code/}
export PYTHONPATH="$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:?set LARB_MODEL_PATH}
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1

cd "$ROOT"
mkdir -p "$OUT"
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 7h \
  "$PY" -m larb_scaled.runner --stage p1-gates --out "$OUT"
