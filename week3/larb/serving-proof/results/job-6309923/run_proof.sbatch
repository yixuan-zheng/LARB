#!/bin/bash
#SBATCH --job-name=qwen3-vllm-proof
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
source vllm-proof-env/bin/activate
export HF_HOME="${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}/hf-cache"
export HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONPATH="$PWD/serving-proof${PYTHONPATH:+:$PYTHONPATH}"
export BUDGET_PROOF_DIR="$PWD/serving-proof/results/job-$SLURM_JOB_ID"
export BUDGET_PORT=$((20000 + SLURM_JOB_ID % 30000))
export BUDGET_MODEL_PATH="$HF_HOME/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
mkdir -p "$BUDGET_PROOF_DIR"
cp stage3/protocol.json stage3/problems100.json "$BUDGET_PROOF_DIR/"
cp serving-proof/*.py serving-proof/run_proof.sbatch "$BUDGET_PROOF_DIR/"
nvidia-smi > "$BUDGET_PROOF_DIR/nvidia-smi.txt"
python -m pip freeze > "$BUDGET_PROOF_DIR/requirements-executed.txt"
timeout --signal=TERM --kill-after=30s 30m python -u serving-proof/prove.py
