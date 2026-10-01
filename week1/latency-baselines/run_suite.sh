#!/usr/bin/env bash
# Drive the FFN-width latency profile in the order that makes it interpretable.
#
# Usage:
#   bash run_suite.sh fast            # harness gate + tiny grids, ~minutes
#   bash run_suite.sh full            # the intended grid, hours
#   SCENARIOS="s1 s3" bash run_suite.sh fast
#   PRESETS="small,large" bash run_suite.sh fast    # if core VRAM is the limit
#   SKIP_S0=1 bash run_suite.sh full
#
# S0 runs first and must pass: it is the only evidence that the instrument can resolve a
# known effect and will not invent one. Everything after it is reported in units of what
# S0 established (alpha ~ 87 us, residual bias ~ 1.4%, implied bandwidth ~ 71% of peak).
#
# One process per preset for S6 and S7 so their peak-VRAM numbers are not polluted by
# other presets' weights. S1/S2/S3/S5 deliberately keep every preset resident in a single
# process, because interleaving presets within one process is what makes the paired
# statistics valid; if all three will not fit, reduce PRESETS rather than serialising.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$here/env.sh"
cd "$here"

GRID="${1:-fast}"
LOG_DIR="$here/run-output/logs"
mkdir -p "$LOG_DIR" "$here/run-output"
PRESETS="${PRESETS:-small,medium,large}"
PRESET_LIST="${PRESETS//,/ }"
SCENARIOS="${SCENARIOS:-s0 s1 s2 s3 s4 s5 s6 s7 s8 s9 s10 s11}"

case "$GRID" in
  fast)
    S1_ARGS="--context-lengths 128,512 --reps 10 --warmup 3"
    S2_ARGS="--prompt-lengths 128,512 --batch-sizes 1,4 --reps 10 --warmup 3"
    S3_ARGS="--context-lengths 1,128 --batch-sizes 1,4 --reps 10 --warmup 3"
    S4_ARGS="--prompt-lengths 128 --batch-sizes 1 --new-tokens 32 --reps 1 --warmup 1"
    S5_ARGS="--prompt-len 256 --batch 4 --backends eager,compile --reps 10 --warmup 3"
    S6_ARGS="--prompt-len 512 --batch 2 --reps 3 --warmup 2"
    S7_ARGS="--prefill-len 512 --batch 1 --capacity-contexts 1 --reps 5 --warmup 2"
    S8_ARGS="--statics small --slice-modes view --prompt-len 256 --batch 2 --reps 8 --warmup 3"
    S9_ARGS="--prompt-lengths 512 --batch-sizes 1 --new-tokens 16 --reps 1 --warmup 1"
    S10_ARGS="--context-lengths 512 --batch-sizes 1 --new-tokens 24 --reps 1 --warmup 1"
    S11_ARGS="--statics small --capacity-contexts 1 --capacity-cap 16"
    ;;
  full)
    S1_ARGS="--context-lengths 128,512,2048,8192 --reps 40 --warmup 10"
    S2_ARGS="--prompt-lengths 128,512,2048,4096 --batch-sizes 1,4,16 --reps 30 --warmup 8"
    S3_ARGS="--context-lengths 1,128,2048 --batch-sizes 1,2,4,8,16,32 --reps 30 --warmup 8"
    S4_ARGS="--prompt-lengths 128,1024 --batch-sizes 1,8 --new-tokens 128 --reps 3 --warmup 1"
    S5_ARGS="--prompt-len 512 --batch 4 --backends eager,compile,cudagraph --reps 40 --warmup 10"
    S6_ARGS="--prompt-len 1024 --batch 8 --reps 5 --warmup 2"
    S7_ARGS="--prefill-len 2048 --batch 4 --capacity-contexts 1,2048 --reps 10 --warmup 3"
    S8_ARGS="--statics small,medium --slice-modes view,materialize --prompt-len 512 --batch 4 --reps 30 --warmup 8"
    S9_ARGS="--prompt-lengths 512,2048 --batch-sizes 1,4 --new-tokens 32 --reps 2 --warmup 1"
    S10_ARGS="--context-lengths 512,2048 --batch-sizes 1,8 --new-tokens 48 --reps 2 --warmup 1"
    S11_ARGS="--statics small,medium --capacity-contexts 1,2048 --capacity-cap 64"
    ;;
  *)
    echo "unknown grid '$GRID' (expected 'fast' or 'full')" >&2
    exit 2
    ;;
esac

tag="$GRID"
run_one() {  # run_one <label> <cmd...>
  local label="$1"; shift
  local log="$LOG_DIR/$label.log"
  echo "--- $label  ($(date -u +%H:%M:%SZ))  -> $log"
  "$@" 2>&1 | tee "$log"
}

has() { case " $SCENARIOS " in *" $1 "*) return 0;; *) return 1;; esac; }

if has s0 && [ -z "${SKIP_S0:-}" ]; then
  run_one "s0_harness_validation_$tag" python -u s0_harness_validation.py --tag "$tag"
fi

for scenario in s1 s2 s3 s5; do
  if has "$scenario"; then
    case "$scenario" in
      s1) extra="$S1_ARGS";;
      s2) extra="$S2_ARGS";;
      s3) extra="$S3_ARGS";;
      s5) extra="$S5_ARGS";;
    esac
    # shellcheck disable=SC2086
    run_one "${scenario}_${tag}" python -u "$scenario"_*.py --presets "$PRESETS" \
      --tag "$tag" $extra
  fi
done

if has s4; then
  for preset in $PRESET_LIST; do
    # shellcheck disable=SC2086
    run_one "s4_end_to_end_${preset}_$tag" python -u s4_end_to_end.py --preset "$preset" \
      --tag "$tag" $S4_ARGS
  done
fi

for scenario in s6 s7; do
  if has "$scenario"; then
    case "$scenario" in
      s6) extra="$S6_ARGS";;
      s7) extra="$S7_ARGS";;
    esac
    for preset in $PRESET_LIST; do
      # shellcheck disable=SC2086
      run_one "${scenario}_${preset}_$tag" python -u "$scenario"_*.py --preset "$preset" \
        --tag "$tag" $extra
    done
  fi
done

# Dynamic switching extension (s8-s11). These build one full-weight switchable model plus
# static references, so they take --statics rather than --presets and run one process each.
for scenario in s8 s9 s10 s11; do
  if has "$scenario"; then
    case "$scenario" in
      s8) extra="$S8_ARGS";;
      s9) extra="$S9_ARGS";;
      s10) extra="$S10_ARGS";;
      s11) extra="$S11_ARGS";;
    esac
    # shellcheck disable=SC2086
    run_one "${scenario}_switch_$tag" python -u "$scenario"_*.py --tag "$tag" $extra
  fi
done

echo "--- aggregating"
run_one "analyze_$tag" python -u analyze_latency.py
# Render immediately: the report is what a reader (and a future decision) sees, and the
# tracked results/latency_report.md must not lag the tracked profile it is derived from.
run_one "report_$tag" python -u report_latency.py

echo "--- suite complete: $GRID grid, presets '$PRESETS'"
