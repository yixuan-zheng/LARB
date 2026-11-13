#!/bin/bash
#SBATCH -A coc
#SBATCH -p ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
#SBATCH --time=03:00:00
#SBATCH --job-name=larb-track-b-full
set -euo pipefail
release=$(realpath "${1:?Track B release directory required}")
python=${2:?pinned serving Python required}
model=${3:?pinned model snapshot required}
out=${4:?absolute Track B run directory required}
[[ "$out" = /* ]]
cd "$release"
export PYTHONDONTWRITEBYTECODE=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false OMP_NUM_THREADS=4 MALLOC_ARENA_MAX=2
export VLLM_WORKER_MULTIPROC_METHOD=spawn VLLM_USE_FLASHINFER_SAMPLER=0
export VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 178m \
    "$python" -B -u run.py --allocation-seconds 10440 --model "$model" --out "$out"
