#!/bin/bash
#SBATCH --job-name=larb-w4-step1
#SBATCH --account=coc
#SBATCH --partition=ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=00:45:00
set -euo pipefail
cd "$HOME/scratch/CS6222-qwen3-baseline"
source vllm-proof-env/bin/activate
export LARB_WEEK3_ROOT="$PWD"
export HF_HOME="$PWD/hf-cache" HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/week4/step1/admission-control:$PWD/burst-policy:$PWD/serving-proof${PYTHONPATH:+:$PYTHONPATH}"
export BURST_OUT="$PWD/week4/step1/admission-control/results/job-$SLURM_JOB_ID"
export BUDGET_PORT=$((20000 + SLURM_JOB_ID % 30000))
export BUDGET_MODEL_PATH="$HF_HOME/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
mkdir "$BURST_OUT"
mkdir "$BURST_OUT/requests"
cp week4/step1/admission-control/spec.json "$BURST_OUT/"
cp week4/step1/admission-control/source-lock.json "$BURST_OUT/"
cp week4/step1/admission-control/source-state.json "$BURST_OUT/"
cp stage3/protocol.json "$BURST_OUT/stage3-protocol.json"
cp stage3/problems100.json "$BURST_OUT/"
nvidia-smi > "$BURST_OUT/nvidia-smi.txt"
python -m pip freeze > "$BURST_OUT/requirements-executed.txt"
python -B -m unittest discover -s week4/step1/admission-control -p 'test_*.py' -v > "$BURST_OUT/cpu-checks.txt" 2>&1
timeout --signal=TERM --kill-after=30s 40m python -B -u week4/step1/admission-control/run_smoke.py
python -B week4/step1/admission-control/validate_smoke.py --root "$BURST_OUT"
