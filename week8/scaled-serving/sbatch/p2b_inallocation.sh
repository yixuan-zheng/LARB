#!/bin/bash
# Run one AIME (P2B) stage inside the current GPU allocation.
#
#   srun --jobid=<ALLOC> --overlap bash sbatch/p2b_inallocation.sh build|plan|calibration|live|freeze|main [extra args]
#
# The environment is fixed here so the stage sees the same venvs, model and
# offline flags as every earlier run. CPU-only stages (build, plan, freeze) can
# also be run directly on the login node.
set -uo pipefail

ROOT=${LARB_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}
WEEK8=${LARB_WEEK8_ROOT:-$ROOT/week8/scaled-serving}
PY=${LARB_PYTHON:-python3}
APY=${LARB_ANALYSIS_PYTHON:-python3}

export PYTHONPATH="$WEEK8/code:$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:?set LARB_MODEL_PATH to the Qwen3-4B checkout}
export LARB_DATA_DIR="$WEEK8/data"
export LARB_WEEK8_ROOT="$WEEK8"
export LARB_ANALYSIS_PYTHON="$APY"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1

STAGE=${1:?usage: p2b_inallocation.sh <stage> [extra args]}
shift || true
OUT=${LARB_OUT:-$WEEK8/results/p2b/calibration}
if [ "$STAGE" = "main" ]; then
  OUT=${LARB_OUT:-$WEEK8/results/p2b/main}
fi

cd "$ROOT" || exit 1
echo "== p2b stage=$STAGE out=$OUT $(date -Is) =="
LARB_OUT="$OUT" "$PY" -m tools.candidate_phase --stage "$STAGE" --out "$OUT" \
  --analysis-python "$APY" "$@"
