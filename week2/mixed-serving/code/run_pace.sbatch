#!/bin/bash
# Mixed-serving harness launcher (GPU): validation gates, cost calibration, runs.
#
#   sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=validate code/run_pace.sbatch
#   sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=calibrate code/run_pace.sbatch
#   sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=serve \
#     code/run_pace.sbatch -- --trace traces/azure_conv_burst.json --rate-scale 1.0 \
#     --policy phase_hybrid
#
# One configuration per job: two timing-sensitive runs must never share the device.
#SBATCH --job-name=mixed-serving
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/scratch/MatFormer-ElasticServing}"
# The Week 1 environment: same venv, same HF cache, same PYTHONPATH.
source "$REPO_ROOT/week1/latency-baselines/env.sh"
cd "${STUDY_ROOT:?Set STUDY_ROOT to the absolute week2/mixed-serving folder}"

MODE="${STUDY_MODE:-validate}"
LOG_DIR="results/logs"
mkdir -p "$LOG_DIR" results/gates results/costs run-output
# Tolerate the conventional 'sbatch script -- args' form.
while [ "${1:-}" = "--" ]; do shift; done
nvidia-smi

case "$MODE" in
  validate)
    python -u code/validate_harness.py --level "${GATE_LEVEL:-full}" --with-trace \
      --out "results/gates/job-${SLURM_JOB_ID}.json" --min-sm-clock-mhz 1500
    ;;
  calibrate)
    python -u code/calibrate.py --mode measure --device cuda \
      --reps "${REPS:-5}" --out results/costs \
      --trace "${TRACE:-traces/azure_conv_steady.json}"
    ;;
  serve)
    # One configuration per job: extra arguments go straight to run_serving.py.
    python -u code/run_serving.py "$@" \
      --reps "${REPS:-3}" --out run-output --results results \
      --gates "${GATES:-cheap}" --tag "job-${SLURM_JOB_ID}"
    ;;
  *)
    echo "STUDY_MODE must be validate | calibrate | serve" >&2
    exit 2
    ;;
esac
