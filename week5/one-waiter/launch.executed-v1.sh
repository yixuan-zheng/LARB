#!/bin/bash
# One Week 5 condition on the allocated interactive H100; no retries.
set -euo pipefail
COND=${1:?usage: launch.sh CONDITION CAP_SECONDS}
CAP=${2:?usage: launch.sh CONDITION CAP_SECONDS}
ENV_ROOT=/home/hice1/jwang3221/scratch/LARB-week5-env
REPO=/home/hice1/jwang3221/scratch/LARB
HERE="$REPO/week5/one-waiter"
source "$ENV_ROOT/venv/bin/activate"
export LARB_WEEK3_ROOT="$REPO/week3/larb"
export HF_HOME="$ENV_ROOT/hf-cache" HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn MALLOC_ARENA_MAX=2
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$HERE:$REPO/week3/larb/burst-policy:$REPO/week3/larb/serving-proof:$REPO/week4/baseline-controls"
export W5_ALLOCATION="${W5_ALLOCATION:-6662944}"
OUT="$HERE/results/job-${W5_ALLOCATION}-${COND}"
export BURST_OUT="$OUT"
export BUDGET_PORT="${BUDGET_PORT:-21234}"
export BUDGET_MODEL_PATH="$ENV_ROOT/model/Qwen3-4B"
mkdir -p "$OUT/requests"
cp "$HERE/plan.json" "$HERE/cohort.json" "$HERE/source-lock.json" "$OUT/"
cp "$HERE/inputs/problems100.json" "$HERE/inputs/dataset-manifest.json" "$OUT/"
cp "$REPO/week3/larb/stage3/protocol.json" "$OUT/stage3-protocol.json"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$OUT/hardware.txt"
python -m pip freeze > "$OUT/requirements-executed.txt"
ls -l "$BUDGET_MODEL_PATH" > "$OUT/model-files.txt"
sha256sum "$BUDGET_MODEL_PATH/model.safetensors.index.json" >> "$OUT/model-files.txt"
pkill -f "VLLM::EngineCore" 2>/dev/null || true
sleep 3
nvidia-smi --query-gpu=memory.used --format=csv,noheader >> "$OUT/hardware.txt"
echo "job=$W5_ALLOCATION condition=$COND cap=${CAP}s out=$OUT started=$(date -Is)"
python -B -u "$HERE/run_week5.py" --condition "$COND" --cap-seconds "$CAP"
python -B "$HERE/validate5.py" --root "$OUT"
echo "finished=$(date -Is)"
pkill -f "VLLM::EngineCore" 2>/dev/null || true
