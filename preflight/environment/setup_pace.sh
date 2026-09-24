#!/usr/bin/env bash
set -euo pipefail
module load anaconda3/2023.03
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
export MATFORMER_PROJECT_ROOT="${MATFORMER_PROJECT_ROOT:-$HOME/scratch/MatFormer-ElasticServing}"
mkdir -p "$MATFORMER_PROJECT_ROOT" "$MATFORMER_PROJECT_ROOT/pip-cache" "$MATFORMER_PROJECT_ROOT/tmp"
python -m venv "$MATFORMER_PROJECT_ROOT/venv"
source "$MATFORMER_PROJECT_ROOT/venv/bin/activate"
export PIP_CACHE_DIR="$MATFORMER_PROJECT_ROOT/pip-cache"
export TMPDIR="$MATFORMER_PROJECT_ROOT/tmp"
python -m pip install --upgrade pip
python -m pip install -r "$repo_root/preflight/environment/requirements.txt"
python -m pip check
python -m pip freeze > "$MATFORMER_PROJECT_ROOT/installed-versions.txt"
printf 'Environment ready. Source preflight/environment/activate_pace.sh, then authenticate Hugging Face.\n'
