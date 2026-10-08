#!/bin/bash
# CPU launcher: the model-backed cache-correctness smoke, the seed cost table, and
# the replay (simulated) smoke.  No GPU is requested, so this can run while another
# job owns the device.
#
#   sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=smoke_cpu code/run_cpu.sbatch
#   sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=seed      code/run_cpu.sbatch
#
#SBATCH --job-name=mixed-serving-cpu
#SBATCH --account=coc
#SBATCH --partition=coc-cpu
#SBATCH --qos=coc-ice
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --time=01:00:00
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$HOME/scratch/MatFormer-ElasticServing}"
source "$REPO_ROOT/week1/latency-baselines/env.sh"
cd "${STUDY_ROOT:?Set STUDY_ROOT to the absolute week2/mixed-serving folder}"
mkdir -p results/logs results/costs

# Tolerate the conventional 'sbatch script -- args' form.
while [ "${1:-}" = "--" ]; do shift; done

case "${STUDY_MODE:-smoke_cpu}" in
  smoke_cpu)
    # Extra arguments pass straight through, so a comma-separated list is safe:
    #   sbatch ... code/run_cpu.sbatch -- --prompt-lengths 24,32,48 --requests 3
    # (sbatch --export splits on commas, so lists must not go through the environment;
    # a dash-separated PROMPT_LENGTHS=24-32-48 also works.)
    LENGTHS="${PROMPT_LENGTHS:-24,48}"
    LENGTHS="${LENGTHS//-/,}"
    python -u code/smoke_cpu_model.py \
      --requests "${REQUESTS:-2}" --output-tokens "${OUTPUT_TOKENS:-2}" \
      --prompt-lengths "$LENGTHS" --dtype "${DTYPE:-float32}" \
      --out results/smoke_cpu_model.json "$@"
    ;;
  unit)
    python -u code/test_serving_cpu.py
    ;;
  seed)
    python -u code/calibrate.py --mode seed --out results/costs \
      --trace "${TRACE:-traces/azure_conv_steady.json}"
    ;;
  replay)
    python -u code/run_serving.py --mode replay --cost-table \
      "${COST_TABLE:-results/costs/cost_table_seed.json}" --out run-output --results results \
      --trace "${TRACE:-traces/azure_conv_burst.json}" --rate-scale "${RATE_SCALE:-1.0}" \
      --tag "replay-${SLURM_JOB_ID}" --gates none --force
    ;;
  *)
    echo "STUDY_MODE must be smoke_cpu | unit | seed | replay" >&2
    exit 2
    ;;
esac
