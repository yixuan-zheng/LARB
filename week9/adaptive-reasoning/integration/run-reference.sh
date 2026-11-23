#!/bin/bash
# Invoke from a preallocated GPU shell. No scheduler side effects.
set -euo pipefail
cd "${1:?supply staged directory}"
export PILOT_ROOT="$PWD"
export PYTHONPATH="$PWD:$PWD/repo/week7/scaled-serving/code"
export LARB_THRESHOLD=1 LARB_MAX_NUM_SEQS=8 SLOTS=8 BLOCK_ID=0
export LARB_MODEL_PATH="${LARB_MODEL_PATH:?path to pinned base snapshot}"
export LARB_ADAPTER="${LARB_ADAPTER:?path to verified adapter directory}"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 VLLM_WORKER_MULTIPROC_METHOD=spawn TOKENIZERS_PARALLELISM=false
export PILOT_EVIDENCE_DIR="${PILOT_EVIDENCE_DIR:-$PWD/evidence}"
exec "${LARB_PYTHON:-python3}" -u replay.py
