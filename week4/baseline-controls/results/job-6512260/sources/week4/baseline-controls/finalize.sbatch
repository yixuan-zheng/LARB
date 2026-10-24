#!/bin/bash
#SBATCH --job-name=larb-fixed-score
#SBATCH --account=coc
#SBATCH --partition=coc-cpu
#SBATCH --qos=coc-ice
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --time=00:30:00
set -euo pipefail
cd "${PACE_PROJECT_ROOT:?}"
source vllm-proof-env/bin/activate
export LARB_WEEK3_ROOT="$PWD"
export PYTHONPATH="$PWD/week4/reserved-validation/.analysis-deps:$PWD/week4/baseline-controls:$PWD/burst-policy:$PWD/serving-proof"
python -B week4/baseline-controls/finalize.py
