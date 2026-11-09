#!/bin/bash
set -euo pipefail
PYTHON=${1:?pinned Python}
MODEL=${2:?pinned model}
RESULTS=${3:?results directory}
CODE=${4:?frozen bundle}
HERE="$CODE/week6/engine-entry-pilot"
ROOT="$RESULTS/job-${SLURM_JOB_ID:?}-engine-entry"

export BUDGET_MODEL_PATH="$MODEL" BUDGET_PORT=18761
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
export PYTHONPATH="$HERE"

mkdir "$ROOT"
cp "$HERE"/{source-lock.json,spec.json,trace-r0.json,trace-r1.json,allocation.json,provenance.json,probe-r0.json,probe-r1.json,DECISION.md,run.sbatch} "$ROOT/"
cd "$CODE"
finish() {
  local status=$?
  trap - EXIT
  "$PYTHON" -B "$HERE/evaluate.py" "$ROOT" || exit 1
  exit "$status"
}
trap finish EXIT
"$PYTHON" -B "$HERE/readiness.py" --runtime
for block in 0 1; do
  out="$ROOT/block$block"
  status=0
  srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 170m \
    "$PYTHON" -B -u "$HERE/run.py" --stage pilot --out "$out" --trace "$HERE/trace-r$block.json" || status=$?
  printf '%s\n' "$status" > "$ROOT/block$block.exit"
  if [ -f "$out/progress.json" ]; then
    "$PYTHON" -B "$HERE/analyze.py" --root "$out"
  fi
  if [ "$status" -ne 0 ]; then exit "$status"; fi
done
