#!/bin/bash
#SBATCH --job-name=qwen3-burst-pilot
#SBATCH --account=coc
#SBATCH --partition=ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
source vllm-proof-env/bin/activate
export HF_HOME="$PWD/hf-cache" HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONPATH="$PWD/burst-policy:$PWD/serving-proof${PYTHONPATH:+:$PYTHONPATH}"
export BURST_OUT="$PWD/burst-policy/results/job-$SLURM_JOB_ID"
export BUDGET_PORT=$((20000 + SLURM_JOB_ID % 30000))
export BUDGET_MODEL_PATH="$HF_HOME/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
mkdir -p "$BURST_OUT/requests"
cp burst-policy/spec.json "$BURST_OUT/"
cp stage3/protocol.json "$BURST_OUT/stage3-protocol.json"
cp stage3/problems100.json "$BURST_OUT/"
cp burst-policy/*.py burst-policy/run_burst.sbatch "$BURST_OUT/"
cp serving-proof/control.py "$BURST_OUT/proof-control.py"
nvidia-smi > "$BURST_OUT/nvidia-smi.txt"
python -m pip freeze > "$BURST_OUT/requirements-executed.txt"
timeout --signal=TERM --kill-after=30s 55m python -u burst-policy/run.py
