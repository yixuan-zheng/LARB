#!/bin/bash
#SBATCH --job-name=decode-study
#SBATCH --account=coc
#SBATCH --partition=coc-gpu
#SBATCH --qos=coc-ice
#SBATCH --gres=gpu:l40s:1
#SBATCH --cpus-per-task=4
#SBATCH --mem=64G
#SBATCH --time=01:00:00
set -euo pipefail
source "$HOME/scratch/CS6222-matformer-local-test/gemma3n/bin/activate"
export HF_HOME="$HOME/scratch/CS6222-matformer-local-test/hf-cache"
export HF_HUB_OFFLINE=1
export TOKENIZERS_PARALLELISM=false
export PYTORCH_ALLOC_CONF=expandable_segments:True
cd "${STUDY_ROOT:?Set STUDY_ROOT to the absolute decode-study folder path}"
case "${STUDY_MODE:-profile}" in
  profile) script=profile_decode.py; group=profile ;;
  timing) script=benchmark.py; group=timing ;;
  *) echo 'STUDY_MODE must be profile or timing' >&2; exit 2 ;;
esac
mkdir -p "results/$group"
nvidia-smi
python -u "code/$script" --out "results/$group/job-${SLURM_JOB_ID}.json" --min-sm-clock-mhz 1500 --strict-clock "$@"
