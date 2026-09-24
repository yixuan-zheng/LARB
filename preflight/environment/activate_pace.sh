# Source from a PACE shell after cloning this repository.
module load anaconda3/2023.03
export MATFORMER_PROJECT_ROOT="${MATFORMER_PROJECT_ROOT:-$HOME/scratch/MatFormer-ElasticServing}"
export HF_HOME="$MATFORMER_PROJECT_ROOT/hf-cache"
export HF_HUB_CACHE="$HF_HOME/hub"
export PIP_CACHE_DIR="$MATFORMER_PROJECT_ROOT/pip-cache"
export TMPDIR="$MATFORMER_PROJECT_ROOT/tmp"
mkdir -p "$HF_HOME" "$PIP_CACHE_DIR" "$TMPDIR"
source "$MATFORMER_PROJECT_ROOT/venv/bin/activate"
