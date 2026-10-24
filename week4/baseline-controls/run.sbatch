#!/bin/bash
#SBATCH --job-name=larb-w4-fixed
#SBATCH --account=coc
#SBATCH --partition=ice-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=04:00:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?Set PACE_PROJECT_ROOT}"
source vllm-proof-env/bin/activate
export LARB_WEEK3_ROOT="$PWD"
export HF_HOME="$PWD/hf-cache" HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$PWD/week4/baseline-controls:$PWD/burst-policy:$PWD/serving-proof${PYTHONPATH:+:$PYTHONPATH}"
export BURST_OUT="$PWD/week4/baseline-controls/results/job-$SLURM_JOB_ID"
export BUDGET_PORT=$((20000 + SLURM_JOB_ID % 30000))
export BUDGET_MODEL_PATH="$HF_HOME/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
mkdir "$BURST_OUT"
mkdir "$BURST_OUT/requests"
cp week4/baseline-controls/plan.json "$BURST_OUT/"
cp week4/baseline-controls/candidate-lock.json "$BURST_OUT/"
cp week4/baseline-controls/spec.json "$BURST_OUT/"
cp week4/baseline-controls/source-lock.json "$BURST_OUT/"
cp week4/baseline-controls/source-state.json "$BURST_OUT/"
cp week4/baseline-controls/inputs/problems100.json "$BURST_OUT/"
cp week4/baseline-controls/inputs/dataset-manifest.json "$BURST_OUT/"
cp week4/baseline-controls/exposure-audit.json "$BURST_OUT/"
cp stage3/protocol.json "$BURST_OUT/stage3-protocol.json"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$BURST_OUT/hardware.txt"
python -m pip freeze > "$BURST_OUT/requirements-executed.txt"
if [ "$VALIDATION_CONDITION" = gate ]; then RUN_MINUTES=110; else RUN_MINUTES=230; fi
timeout --signal=TERM --kill-after=60s "${RUN_MINUTES}m" python -B -u week4/baseline-controls/run_validation.py
python -B week4/baseline-controls/validate.py --root "$BURST_OUT"
python -B week4/step1/controlled-comparison/checks/pack_events.py --root "$BURST_OUT"

if [ "$VALIDATION_CONDITION" = gate ]; then
  PYTHONPATH="$PWD/week4/reserved-validation/.analysis-deps:$PYTHONPATH" python -B week4/baseline-controls/analyze.py --root "$BURST_OUT"
fi
