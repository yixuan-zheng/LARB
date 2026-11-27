#!/bin/bash
# Forced-cue smoke, then the 24-item Omni-MATH preview, inside an existing GPU
# allocation (run with `srun --jobid=<id> --overlap bash <this script>`).
# The layout mirrors run_all (smoke/, preview/) so the records are directly
# comparable with a full qualification sequence.
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

OUT=$WEEK8/results/p2a-pilot
cd "$ROOT" || exit 1
mkdir -p "$OUT"

echo "== smoke $(date -Is) =="
LARB_OUT="$OUT/smoke" "$PY" -m larb_week8.runner --stage smoke \
  --out "$OUT/smoke" --analysis-python "$APY" || { echo "SMOKE_FAILED"; exit 1; }

echo "== preview-24 $(date -Is) =="
LARB_OUT="$OUT/preview" "$PY" -m larb_week8.runner --stage preview \
  --out "$OUT/preview" --analysis-python "$APY" || { echo "PREVIEW_FAILED"; exit 1; }

echo "== stage1 done $(date -Is) =="
