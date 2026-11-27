#!/bin/bash
# Candidate pool preview inside the current GPU allocation (AIME 2025+2026).
set -uo pipefail

ROOT=${LARB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}
WEEK8=$ROOT/week8/scaled-serving
PY=${LARB_PYTHON:-python3}
APY=${LARB_ANALYSIS_PYTHON:-python3}

export PYTHONPATH="$WEEK8/code:$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:?set LARB_MODEL_PATH to the Qwen3-4B checkout}
export LARB_DATA_DIR="$WEEK8/data"
export LARB_WEEK8_ROOT="$WEEK8"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1

OUT=$WEEK8/results/p2b
cd "$ROOT" || exit 1

echo "== candidate preview $1 $(date -Is) =="
LARB_OUT="$OUT/preview$1" "$PY" -m tools.run_candidate_preview --size "$1" \
  --out "$OUT/preview$1" --analysis-python "$APY" || { echo "CANDIDATE_FAILED"; exit 1; }
echo "== done $(date -Is) =="
