#!/bin/bash
set -euo pipefail
cd "${1:?staged root required}"
SERVING_PYTHON=${2:?serving Python required}
MODEL_PATH=${3:?model path required}
export PYTHONPATH="$PWD/week6/shared-prefix-study"
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 230m \
    "$SERVING_PYTHON" -B -u week6/shared-prefix-study/run.py \
    --model "$MODEL_PATH" --out "$PWD/job-${SLURM_JOB_ID:?}"
