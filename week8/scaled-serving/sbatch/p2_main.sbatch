#!/bin/bash
# Week 8 P2 main run, only after p2a_qualify has written a GO decision and a
# frozen config. This script does not submit itself.
#SBATCH --job-name=larb-p2-omni
#SBATCH --partition=ice-gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=16:00:00
set -uo pipefail

ROOT=${LARB_ROOT:?set LARB_ROOT to the repository root}
PY=${LARB_PYTHON:?set LARB_PYTHON to the serving venv python}
APY=${LARB_ANALYSIS_PYTHON:?set LARB_ANALYSIS_PYTHON to the analysis venv python}
WEEK8=${LARB_WEEK8_ROOT:-$ROOT/week8/scaled-serving}
OUT=${LARB_OUT:-$WEEK8/results/p2-main}
export PYTHONPATH="$WEEK8/code:$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:?set LARB_MODEL_PATH to the local Qwen3-4B directory}
export LARB_DATA_DIR="$WEEK8/data"
export LARB_OUT="$OUT"
export LARB_WEEK8_ROOT="$WEEK8"
export LARB_ANALYSIS_PYTHON="$APY"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1

cd "$ROOT"
if [ ! -f "$WEEK8/configs/p2_main_frozen.json" ]; then
  echo "P2 is not frozen; run p2a_qualify and read decision.json first." >&2
  exit 2
fi
mkdir -p "$OUT"

srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 15h \
  "$PY" -m larb_week8.runner --stage main --out "$OUT"
