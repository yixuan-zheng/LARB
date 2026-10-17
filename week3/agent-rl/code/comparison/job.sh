#!/bin/bash
#SBATCH --job-name=agent-rl-tools
#SBATCH --partition=ice-bw-gpu
#SBATCH --gres=gpu:rtx_pro_6000_blackwell:1
#SBATCH --cpus-per-task=2
#SBATCH --mem=32G
#SBATCH --time=00:20:00
#SBATCH --output=slurm-%j.out
set -euo pipefail
cd "${AGENT_RL_ROOT:?Set AGENT_RL_ROOT to the experiment directory}"
export PATH=$PWD/env/bin:$PATH
TASK_ROOT=$(pwd -P)
export PYTHONPATH=$TASK_ROOT/areal:$TASK_ROOT:$TASK_ROOT/areal/examples/tir
export SLOT_POLICY=native
export DYNAMIC_SAMPLING=0
export OMP_NUM_THREADS=4
export PYTORCH_ALLOC_CONF=expandable_segments:True
export TOKENIZERS_PARALLELISM=false
export PYTHONUNBUFFERED=1
export WANDB_MODE=disabled
export VLLM_WORKER_MULTIPROC_METHOD=spawn
export TMPDIR=/tmp/agent-rl-$SLURM_JOB_ID
mkdir -p "$TMPDIR"
export HF_HUB_DISABLE_XET=1
export TRITON_CACHE_DIR=$TASK_ROOT/tau-kernel-cache/triton
export TORCHINDUCTOR_CACHE_DIR=$TASK_ROOT/tau-kernel-cache/inductor
nvidia-smi > gpu-provenance-$SLURM_JOB_ID.txt
nvidia-smi --query-gpu=timestamp,index,uuid,utilization.gpu,memory.used,power.draw --format=csv -l 1 > gpu-metrics-$SLURM_JOB_ID.csv &
MONITOR_PID=$!
trap 'kill "$MONITOR_PID" 2>/dev/null || true' EXIT
for mode in tirgatecompare; do
  export PROFILE_DIR=$PWD/profiles/$mode
  mkdir -p "$PROFILE_DIR"
  printf 'START_MODE %s\n' "$mode"
  python engine_metrics.py "$mode-run.log" "$mode-engine-metrics.jsonl" 1140 &
  timeout --signal=TERM --kill-after=20 1140 python run_tir_comparison.py --config "$mode.yaml" > "$mode-run.log" 2>&1 || {
    printf 'FAILED_MODE %s\n' "$mode"
    tail -30 "$mode-run.log"
    exit 1
  }
  printf 'COMPLETE_MODE %s\n' "$mode"
done
