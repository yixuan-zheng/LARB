#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:00:00
set -euo pipefail
cd "${STAGE_B_ROOT:?}"
sha256sum -c input.sha256
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$PWD/repo/week7/scaled-serving/code"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
export LARB_THRESHOLD=1 LARB_MAX_NUM_SEQS=4 LARB_OUT="$PWD/smoke"
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
py="$base/vllm-proof-env/bin/python"
status=0
timeout --kill-after=20s 170m "$py" -u math_run.py smoke || status=$?
"$py" grid_summary.py "$PWD" > grid.jsonl
"$py" analyze.py "$PWD" > findings.jsonl
exit "$status"
