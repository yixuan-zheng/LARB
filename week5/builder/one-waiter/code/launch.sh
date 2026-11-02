#!/bin/bash
# One Week 5 condition on the allocated interactive H100; no retries.
set -uo pipefail
COND=${1:?usage: launch.sh CONDITION CAP_SECONDS}
CAP=${2:?usage: launch.sh CONDITION CAP_SECONDS}
# Everything below is resolved from this file, so the checkout can live anywhere.
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # week5/builder/one-waiter/code
ONE_WAITER="$(dirname "$CODE")"                        # week5/builder/one-waiter
REPO="$(cd "$ONE_WAITER/../../.." && pwd)"             # repository root
# Serving environment. Nothing outside the checkout is assumed: override with
# LARB_W5_ENV_ROOT to point at a real venv/model/cache tree.
ENV_ROOT="${LARB_W5_ENV_ROOT:-$REPO/.w5-env}"
source "$ENV_ROOT/venv/bin/activate"
export LARB_WEEK3_ROOT="$REPO/week3/larb"
export HF_HOME="$ENV_ROOT/hf-cache" HF_HUB_OFFLINE=1 TOKENIZERS_PARALLELISM=false
export OMP_NUM_THREADS=4 VLLM_WORKER_MULTIPROC_METHOD=spawn MALLOC_ARENA_MAX=2
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN
export PYTHONDONTWRITEBYTECODE=1
export PYTHONPATH="$CODE:$REPO/week3/larb/burst-policy:$REPO/week3/larb/serving-proof:$REPO/week4/baseline-controls"
export W5_ALLOCATION="${W5_ALLOCATION:-6662944}"
OUT="$ONE_WAITER/results/job-${W5_ALLOCATION}-${COND}"
if [ -e "$OUT" ]; then
  echo "ABORT: $OUT already exists; move it aside instead of overwriting evidence" >&2
  exit 4
fi
export BURST_OUT="$OUT"
export BUDGET_PORT="${BUDGET_PORT:-21234}"
export BUDGET_MODEL_PATH="$ENV_ROOT/model/Qwen3-4B"
mkdir -p "$OUT/requests"
cp "$ONE_WAITER/config/plan.json" "$ONE_WAITER/config/cohort.json" \
   "$ONE_WAITER/config/source-lock.json" "$OUT/"
cp "$ONE_WAITER/inputs/problems100.json" "$ONE_WAITER/inputs/dataset-manifest.json" "$OUT/"
cp "$REPO/week3/larb/stage3/protocol.json" "$OUT/stage3-protocol.json"
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv > "$OUT/hardware.txt"
python -m pip freeze > "$OUT/requirements-executed.txt"
ls -l "$BUDGET_MODEL_PATH" > "$OUT/model-files.txt"
sha256sum "$BUDGET_MODEL_PATH/model.safetensors.index.json" >> "$OUT/model-files.txt"
cleanup() { pkill -f '^VLLM::EngineCore$' 2>/dev/null || true; sleep 1; pkill -9 -f '^VLLM::EngineCore$' 2>/dev/null || true; }
trap cleanup EXIT
cleanup
nvidia-smi --query-gpu=memory.used --format=csv,noheader >> "$OUT/hardware.txt"
echo "job=$W5_ALLOCATION condition=$COND cap=${CAP}s out=$OUT started=$(date -Is)" | tee "$OUT/run.log"
python -B -u "$CODE/run_week5.py" --condition "$COND" --cap-seconds "$CAP" 2>&1 | tee -a "$OUT/run.log"
RUNNER_EXIT=${PIPESTATUS[0]}
python -B "$CODE/validate5.py" --root "$OUT" >> "$OUT/run.log" 2>&1
VALID_EXIT=$?
echo "runner_exit=$RUNNER_EXIT validation_exit=$VALID_EXIT finished=$(date -Is)" | tee -a "$OUT/run.log"
exit "$RUNNER_EXIT"
