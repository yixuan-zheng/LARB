#!/bin/bash
#SBATCH --partition=coc-gpu
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=03:04:00
set -euo pipefail
cd "${PILOT_ROOT:?}"
sha256sum -c input.sha256
base="$HOME/scratch/CS6222-qwen3-baseline"
export PYTHONPATH="$PWD/repo/week7/scaled-serving/code"
export LARB_THRESHOLD=1 LARB_MAX_NUM_SEQS=4
export LARB_MODEL_PATH="$base/hf-cache/hub/models--Qwen--Qwen3-4B/snapshots/1cfa9a7208912126459214e8b04321603b3df60c"
node_dir=$(mktemp -d /tmp/larb-load-pilot.XXXXXXXX)
export PILOT_EVIDENCE_DIR="$node_dir/evidence"
echo "Writing replay evidence on $(hostname) to $PILOT_EVIDENCE_DIR"
nvidia-smi --query-gpu=timestamp,memory.used,utilization.gpu --format=csv -l 5 > gpu.csv &
sampler=$!
archive_evidence() {
    status=$?
    kill "$sampler" 2>/dev/null || true
    if [[ -d "$PILOT_EVIDENCE_DIR" ]]; then
        if ! cp -a "$PILOT_EVIDENCE_DIR" "$PWD/evidence-$SLURM_JOB_ID"; then
            echo "Evidence archive failed. Node-local copy: $PILOT_EVIDENCE_DIR" >&2
            exit 1
        fi
    fi
    rm -rf "$node_dir"
    exit "$status"
}
trap archive_evidence EXIT
timeout --kill-after=20s 176m "$base/vllm-proof-env/bin/python" -u pilot.py "$@"
