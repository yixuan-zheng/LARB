# Source before running any scenario in this directory.
#   source week1/latency-baselines/env.sh
# Mirrors the layout used by preflight/environment/activate_pace.sh: the checkpoint
# cache and local caches live under MATFORMER_PROJECT_ROOT, never under $HOME.
export MATFORMER_PROJECT_ROOT="${MATFORMER_PROJECT_ROOT:-$HOME/scratch/MatFormer-ElasticServing}"
export HF_HOME="$MATFORMER_PROJECT_ROOT/hf-cache"
export HF_HUB_CACHE="$HF_HOME/hub"
export PIP_CACHE_DIR="$MATFORMER_PROJECT_ROOT/pip-cache"
export TMPDIR="$MATFORMER_PROJECT_ROOT/tmp"
export PYTORCH_ALLOC_CONF="${PYTORCH_ALLOC_CONF:-expandable_segments:True}"
export LATENCY_BASELINES_DIR="$MATFORMER_PROJECT_ROOT/week1/latency-baselines"
export PYTHONPATH="$LATENCY_BASELINES_DIR:${PYTHONPATH:-}"
mkdir -p "$HF_HOME" "$PIP_CACHE_DIR" "$TMPDIR"
# shellcheck disable=SC1091
source "$MATFORMER_PROJECT_ROOT/venv/bin/activate"
