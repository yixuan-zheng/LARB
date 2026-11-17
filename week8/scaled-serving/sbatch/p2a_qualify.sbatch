#!/bin/bash
# Week 8 P2A qualification job: preview -> 240 s calibration -> live check.
# This script does not submit itself. It is a documented stop if any gate fails.
#SBATCH --job-name=larb-p2a-qualify
#SBATCH --partition=ice-gpu
#SBATCH --gres=gpu:h100:1
#SBATCH --cpus-per-task=8
#SBATCH --mem=64G
# A 12 h request covers the 13 coarse rates plus the one pre-declared refinement
# round and the live check when queue drain is slow; the inner timeout is 11 h so
# the runner still writes its decision record. Submit from the repository root so
# the relative log path resolves.
#SBATCH --time=12:00:00
#SBATCH --output=week8/scaled-serving/logs/p2a-%j.out
#SBATCH --error=week8/scaled-serving/logs/p2a-%j.err
set -uo pipefail

ROOT=${LARB_ROOT:?set LARB_ROOT to the repository root}
PY=${LARB_PYTHON:?set LARB_PYTHON to the serving venv python}
APY=${LARB_ANALYSIS_PYTHON:?set LARB_ANALYSIS_PYTHON to the analysis venv python}
WEEK8=${LARB_WEEK8_ROOT:-$ROOT/week8/scaled-serving}
OUT=${LARB_OUT:-$WEEK8/results/p2a}
export PYTHONPATH="$WEEK8/code:$ROOT/week7/scaled-serving/code"
export LARB_MODEL_PATH=${LARB_MODEL_PATH:?set LARB_MODEL_PATH to the local Qwen3-4B directory}
export LARB_DATA_DIR="$WEEK8/data"
export LARB_OUT="$OUT"
export LARB_WEEK8_ROOT="$WEEK8"
export HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export TOKENIZERS_PARALLELISM=false VLLM_WORKER_MULTIPROC_METHOD=spawn
export VLLM_USE_FLASHINFER_SAMPLER=0 VLLM_ATTENTION_BACKEND=FLASH_ATTN VLLM_USE_V1=1

cd "$ROOT"
mkdir -p "$OUT"

# Two-environment transition check: the serving venv validates the exact
# tokenizer context; the analysis venv validates Math-Verify and the safe
# grading rule. Both must pass before a GPU hour is spent.
"$PY" -m larb_week8.transition --skip-grading --no-lock \
  --out "$OUT/transition-serving.json" || exit 1
"$APY" -m larb_week8.transition --skip-context --no-lock \
  --out "$OUT/transition-analysis.json" || exit 1

# A documented stop is a successful outcome; the runner writes STOP.md and
# exits zero when a gate fails. A nonzero exit means the rig itself failed.
srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s 11h \
  "$PY" -m larb_week8.runner --stage all --out "$OUT" --analysis-python "$APY"
