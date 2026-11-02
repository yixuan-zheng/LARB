#!/bin/bash
# Resource flags must be supplied explicitly at later reviewed submission.
set -uo pipefail
SERVING_PYTHON=${1:?Python path}
MODEL_PATH=${2:?model snapshot}
OUT_ROOT=${3:?result root}
CODE_ROOT=${4:?frozen code root}
STAGE=${5:?mechanics,calibration,or pilot}
TRACE=${6:-}
HERE="$CODE_ROOT/week5/pressure-followup/serving"
export BUDGET_MODEL_PATH="$MODEL_PATH" BUDGET_PORT=18761
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
export PYTHONPATH="$HERE"
OUT="$OUT_ROOT/job-${SLURM_JOB_ID:?}-${STAGE}"
mkdir -p "$OUT_ROOT"
cd "$CODE_ROOT"
"$SERVING_PYTHON" -B "$HERE/readiness.py" --runtime || exit $?
if [ "$STAGE" = mechanics ]; then
  srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 50m "$SERVING_PYTHON" -B -u "$HERE/mechanics.py" --out "$OUT"
  exit $?
fi
ARGS=(--stage "$STAGE" --out "$OUT")
LIMIT=100m
if [ "$STAGE" = pilot ]; then
  [ -n "$TRACE" ] || exit 2
  ARGS+=(--trace "$TRACE")
  LIMIT=340m
elif [ "$STAGE" != calibration ]; then exit 2; fi
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s "$LIMIT" "$SERVING_PYTHON" -B -u "$HERE/run.py" "${ARGS[@]}"
RUN_EXIT=$?
if [ -f "$OUT/progress.json" ]; then
  "$SERVING_PYTHON" -B "$HERE/analyze.py" --root "$OUT"
  ANALYSIS_EXIT=$?
else ANALYSIS_EXIT=1; fi
if [ "$RUN_EXIT" -ne 0 ]; then exit "$RUN_EXIT"; fi
exit "$ANALYSIS_EXIT"
