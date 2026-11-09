#!/bin/bash
set -uo pipefail
SERVING_PYTHON=${1:?}
MODEL_PATH=${2:?}
RESULT_ROOT=${3:?}
CODE_ROOT=${4:?}
cd "$CODE_ROOT"
HERE="$CODE_ROOT/week6/shared-prefix-study"
export PYTHONPATH="$HERE"
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
OUT="$RESULT_ROOT/job-${SLURM_JOB_ID:?}-shared-prefix"
mkdir -p "$RESULT_ROOT"
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 340m "$SERVING_PYTHON" -B -u "$HERE/run.py" --model "$MODEL_PATH" --out "$OUT"
RUN_EXIT=$?
"$SERVING_PYTHON" -B "$HERE/analyze.py" "$OUT"
ANALYSIS_EXIT=$?
printf 'run_exit=%s analysis_exit=%s\n' "$RUN_EXIT" "$ANALYSIS_EXIT"
if [ "$RUN_EXIT" -ne 0 ]; then exit "$RUN_EXIT"; fi
exit "$ANALYSIS_EXIT"
