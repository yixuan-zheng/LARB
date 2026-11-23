#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=02:30:00
set -euo pipefail
cd "${PILOT_ROOT:?}"
sha256sum -c input.sha256
if [[ "$SLOTS" == 8 ]]; then
    control="../four-$BLOCK_ID"
    job=$(cat "$control/job-id")
    if [[ ! -s "$control/evidence-$job/pilot-summary.json" ]]; then
        echo "No timing-valid four-slot result for this block."
        exit 1
    fi
fi
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$PWD:$PWD/repo/week7/scaled-serving/code"
export LARB_THRESHOLD=1 LARB_MAX_NUM_SEQS="$SLOTS"
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
export LARB_ADAPTER="$PWD/adapter"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn TOKENIZERS_PARALLELISM=false
temp=$(mktemp -d /tmp/larb-replication.XXXXXXXX)
export PILOT_EVIDENCE_DIR="$temp/evidence"
finish() {
    rc=$?
    if [[ -d "$PILOT_EVIDENCE_DIR" ]]; then
        cp -a "$PILOT_EVIDENCE_DIR" "$PILOT_ROOT/evidence-$SLURM_JOB_ID" || exit 1
    fi
    rm -rf "$temp"
    exit "$rc"
}
trap finish EXIT
timeout --kill-after=10s 143m "$base/vllm-proof-env/bin/python" -u replay.py
