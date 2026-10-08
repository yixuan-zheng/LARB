#!/usr/bin/env bash
# FFN-width latency profile for one interactive allocation, sized from measurement.
#
#   SCENARIOS="s2 s3 s5" bash run_session.sh      # resume any subset
#   bash run_session.sh                            # all scenarios
#
# Sizing was corrected after the first session: the sweep cost per iteration is small
# (~0.19 s at 128 context, batch 1) but grows with `batch * prompt_length`, and the
# pathological corner `batch 16 x context 2048` (32768 tokens per prefill) would have
# exceeded the S3 timeout on its own. S3 is therefore split into two runs (s3a: context
# 1/128/2048 at batch 1/4; s3b: context 1/128 at batch 8/16) so batch and context are both
# covered without the product, and every scenario carries a `timeout` because a finite
# allocation must not be lost to one runaway grid point.
set -uo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck disable=SC1091
source "$here/env.sh"
cd "$here"

LOG_DIR="$here/run-output/logs"
STATUS="$here/run-output/session_status.txt"
mkdir -p "$LOG_DIR"
START=$SECONDS
P="small,medium,large"
C="--min-sm-clock-mhz 1500"
SCENARIOS="${SCENARIOS:-s1 s2 s3 s4 s5 s6 s7 s8 s9 s10 s11}"

record() { echo "$1" | tee -a "$STATUS"; }
has() { case " $SCENARIOS " in *" $1 "*) return 0;; *) return 1;; esac; }

run() {  # run <label> <timeout_s> <cmd...>
  local label="$1" secs="$2"; shift 2
  local log="$LOG_DIR/$label.log"
  local t0=$SECONDS
  record "[$(date -u +%H:%M:%S)] START $label (cap ${secs}s)"
  if timeout -k 30 "$secs" "$@" >"$log" 2>&1; then
    record "  OK   $label  $((SECONDS - t0))s"
  else
    record "  FAIL $label  rc=$?  $((SECONDS - t0))s  (log: $log)"
    grep -E 'Error|error|Traceback|assert|FAIL' "$log" | tail -5 | sed 's/^/        /' | tee -a "$STATUS"
  fi
}

record ""
record "=== session2 start $(date -u '+%F %T')  job=${SLURM_JOB_ID:-local}  scenarios='$SCENARIOS'"
record "slurm: $(squeue -j "${SLURM_JOB_ID:-0}" -h -o '%M elapsed, %L left' 2>/dev/null || echo n/a)"

if has s1; then
  # shellcheck disable=SC2086
  run s1_decode_step 900 python -u s1_decode_step.py --presets "$P" --tag session \
    --context-lengths 128,512,2048 --reps 20 --warmup 6 $C
fi
if has s2; then
  # Prefill is the best case for a width win: one large GEMM per projection instead of a
  # skinny GEMV, so the fixed per-kernel cost is amortised over batch * prompt_length.
  # shellcheck disable=SC2086
  run s2_prefill 1500 python -u s2_prefill.py --presets "$P" --tag session \
    --prompt-lengths 128,512,2048 --batch-sizes 1,4 --reps 12 --warmup 4 $C
fi
if has s3; then
  # shellcheck disable=SC2086
  run s3_batch_decode_a 1200 python -u s3_batch_decode.py --presets "$P" --tag session \
    --context-lengths 1,128,2048 --batch-sizes 1,4 --reps 10 --warmup 3 $C
  # shellcheck disable=SC2086
  run s3_batch_decode_b 900 python -u s3_batch_decode.py --presets "$P" --tag s3b \
    --context-lengths 1,128 --batch-sizes 8,16 --reps 10 --warmup 3 $C
fi
if has s4; then
  for preset in small medium large; do
    # shellcheck disable=SC2086
    run "s4_end_to_end_${preset}" 600 python -u s4_end_to_end.py --preset "$preset" --tag session \
      --prompt-lengths 128,1024 --batch-sizes 1,8 --new-tokens 96 --reps 2 --warmup 1 $C
  done
fi
if has s5; then
  # Prefill workload: static shapes and no past_key_values, so it is legitimately graph
  # capturable. A decode step with a mutating cache is not, and is not faked.
  # shellcheck disable=SC2086
  run s5_backends 2400 python -u s5_backends.py --presets "$P" --tag session \
    --prompt-len 512 --batch 4 --backends eager,compile,cudagraph --reps 20 --warmup 5 $C
fi
if has s6; then
  for preset in small medium large; do
    # shellcheck disable=SC2086
    run "s6_layer_profile_${preset}" 600 python -u s6_layer_profile.py --preset "$preset" \
      --tag session --prompt-len 1024 --batch 8 --reps 5 --warmup 2 $C
  done
fi
if has s7; then
  for preset in small medium large; do
    # shellcheck disable=SC2086
    run "s7_memory_${preset}" 600 python -u s7_memory_roofline.py --preset "$preset" --tag session \
      --prefill-len 1024 --batch 2 --capacity-contexts 1,512 --capacity-cap 64 \
      --reps 10 --warmup 3 $C
  done
fi

# Dynamic switching extension (s8-s11). Each builds one full-weight switchable model plus
# the static references it compares against, so it runs as a single process with --statics.
if has s8; then
  # The gate: equivalence, switch-operation cost, mechanism tax and cold-switch penalty.
  # Cheap (small prompts) and must pass before the schedule scenarios mean anything.
  # shellcheck disable=SC2086
  run s8_switch_mechanism 1200 python -u s8_switch_mechanism.py --tag session \
    --statics small,medium --slice-modes view,materialize --prompt-len 512 --batch 4 \
    --reps 20 --warmup 5 $C
fi
if has s9; then
  # shellcheck disable=SC2086
  run s9_switch_phase 1800 python -u s9_switch_phase.py --tag session \
    --prompt-lengths 512,2048 --batch-sizes 1,4 --new-tokens 32 --reps 2 --warmup 1 $C
fi
if has s10; then
  # shellcheck disable=SC2086
  run s10_switch_iteration 1800 python -u s10_switch_iteration.py --tag session \
    --context-lengths 512,2048 --batch-sizes 1,8 --new-tokens 48 --reps 2 --warmup 1 $C
fi
if has s11; then
  # shellcheck disable=SC2086
  run s11_switch_flexibility 900 python -u s11_switch_flexibility.py --tag session \
    --statics small,medium --capacity-contexts 1,2048 --capacity-cap 128 $C
fi

run analyze_latency 300 python -u analyze_latency.py
run report_latency 120 python -u report_latency.py

record "=== session2 end $(date -u '+%F %T')  total $((SECONDS - START))s"
