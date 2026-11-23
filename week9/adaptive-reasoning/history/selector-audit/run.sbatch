#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --time=00:20:00
set -euo pipefail
cd "${AUDIT_ROOT:?}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_USE_V1=1
base="$HOME/scratch/CS6222-qwen3-baseline"
export AUDIT_MODEL="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
timeout --kill-after=15s 17m "$base/vllm-proof-env/bin/python" -u probe.py
python3 -B score.py > audit.json
