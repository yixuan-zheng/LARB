# Week 8 scaled serving: qualification package

**Status:** the one GPU qualification job ran on 2026-11-16 and **stopped at the
24-item preview**: the Omni-MATH fallback pool shows no 4k→8k budget slope
(8/24 at 4k, 7/24 at 8k, -4.2 points; 8k accuracy 29.2%). P2 is not authorised
and `configs/p2_main_frozen.json` does not exist. See
[reports/P2A-STATUS.md](reports/P2A-STATUS.md) and `results/p2a/STOP.md`.

A follow-up in the same allocation explains that result and tests the next
candidate. [reports/SLOPE-ANALYSIS.md](reports/SLOPE-ANALYSIS.md) shows the
slope lives in the AIME family (+17.2 points on 87 paired responses, p = 0.0015)
and not in Omni-MATH, HMMT or the 2025-2026 mix (−2.9 on 69 pairs). The
pre-declared candidate `aime-2025-2026-v1` then reached **+8.3 points** with
41.7% at 8k and no derailments, but 20.8% of 8k answers exhausted the
2,048-token answer allowance, so the gate returns **`inconclusive_grader`** — a
stop that names the legacy contract, not the pool, as the blocker.

An exploratory 48-item run in the same allocation measured **+18.8 points**
(18/48 → 27/48 at 8k, p = 0.022) and a second seed reproduced it exactly
(+18.8; 96 responses combined, p = 5.3e-4). Re-measuring the same 24 questions
inside the 48-item traces reproduced **0 of 48 token sequences** and raised
their gain from +8.3 to +20.8/+25.0, so the single-wave 24-item trace
systematically understates the 8k arm. Gate shape and answer space are the next
pre-measurement decisions, not another measurement of this pool.


This folder builds on [week7/scaled-serving](../../week7/scaled-serving/README.md)
rather than replacing it. The frozen week 7 package remains the rig; this
package adds the pool decision, the 2023 AIME evidence audit, the Omni-MATH
fallback pool, the 240 s calibration design, the GPU transition scaffolding and
the executed qualification record.

## Start here

| Document | What it answers |
|---|---|
| [reports/P2A-STATUS.md](reports/P2A-STATUS.md) | The GPU verdict: preview stop, why, what is settled, what is open, the next action |
| [reports/SLOPE-ANALYSIS.md](reports/SLOPE-ANALYSIS.md) | Why the 4k→8k slope disappeared (156 paired responses by family) and the next candidate pool |
| [reports/P2A-DECISION.md](reports/P2A-DECISION.md) | The qualification decision record: preview numbers, what was not run, open limitations |
| [reports/POOL-DECISION.md](reports/POOL-DECISION.md) | Does the 2023 AIME intersection carry a slope? Is it a usable main pool? Which fallback pool was pre-declared and why? |
| [reports/P1-SCREEN-AUDIT.md](reports/P1-SCREEN-AUDIT.md) | Per-pool 4k/6k/8k numbers, the grading-contract defects and the prompt audit |
| [reports/P2A-QUALIFICATION-PLAN.md](reports/P2A-QUALIFICATION-PLAN.md) | The GPU job order, transition risks, commands and pass/fail records, and how the run was executed |
| [reports/PRECALIBRATION-240.md](reports/PRECALIBRATION-240.md) | Why the 240 s grid is 600-1200/h and why the CPU simulation is not a point predictor |
| [configs/qualify.json](configs/qualify.json) | The frozen preview, calibration and live-check rules |

## What was decided before measurement (CPU)

1. **The 2023 AIME subset is a valid slope witness, not a main pool.** The 24
   measured AIME 2023 items show +29.2 points from 4k to 8k (6/24 to 13/24),
   70.8% answer change, 54.2% accuracy at 8k and an 8.3% cap rate. The HMMT
   2024 half does not carry the slope (+4.2 points) and contains five
   `\dfrac` grading false negatives. The aggregate P1 screen pass is carried
   by AIME 2023.
2. **25 AIME 2023 items cannot resolve 5-6 points.** At 4 seeds the MDE is
   about 16-21 points. The AIME intersection therefore fails the "credible
   main pool" test even though it passes the slope test.
3. **The pre-declared fallback is Omni-MATH hard, `omni-math-hard-v1`.** It is
   filtered by published difficulty (5.0-8.0), source-diverse (59 sources),
   self-gradable and context-safe. The cohort is 240 signal items: 216 main,
   24 preview, 24 escalation, 48 calibration, 92 reused filler.
4. **The deadline is 240 s.** The P1 180 s calibration has no 15-40% band
   (0% at 800/h, 74.7% at 931/h). The 240 s grid is 600-1200/h, 25 minutes per
   rate, with a 10-minute warm-up and a pre-declared one-round refinement.
5. **The grading rule is stricter than P1.** Exact normalised match first;
   Math-Verify only when its parse is not lossy. This rejects both the
   `\dfrac` false negatives and the radical-expression false positive found in
   the P1 records.

## Directory map

| Path | What it is |
|---|---|
| `code/larb_week8/` | Week 8 pool, traces, preview/calibration analysis, decision, GPU runner and transition check. Imports the frozen week 7 code; does not copy it. |
| `code/tools/` | `build_omni_pool.py`, `build_traces.py`, `audit_p1_screen.py`, `analyze_slope_history.py`, `build_candidate_pool.py`, `run_candidate_preview.py` |
| `code/tests/` | Synthetic end-to-end tests for the preview and calibration analyzers |
| `configs/` | Pool, qualification and withheld P2 draft; `pool_aime_2025_2026.json` is the candidate pre-declaration |
| `data/` | Raw source snapshot and processed Omni-MATH questions; `data/candidates/` holds the AIME candidate set (gitignored outputs) |
| `artifacts/` | Cohort, traces, source lock; `artifacts/traces-candidates/` holds the candidate preview traces |
| `results/`, `logs/` | Local outputs (gitignored): `results/p2a` is the Omni qualification, `results/p2b` the candidate preview |
| `sbatch/` | Qualification and P2 main scripts, the in-allocation stage scripts and `p2b_candidate_preview.sh`; none submits itself |

## CPU checks (login node)

The one-command reproduction is:

```sh
bash week8/scaled-serving/code/tools/run_cpu_all.sh
```

It rebuilds the pool and traces, runs the P1 audit, the pre-calibration, the
unit tests and both transition checks, and writes the source lock. The
individual commands are:

```sh
export ROOT=/home/hice1/jwang3221/scratch/LARB
export WEEK8=$ROOT/week8/scaled-serving
export PYTHONPATH=$WEEK8/code:$ROOT/week7/scaled-serving/code

# Rebuild the pool and traces
/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python \
  $WEEK8/code/tools/build_omni_pool.py
/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python \
  $WEEK8/code/tools/build_traces.py --stage all

# Evidence audit and pre-calibration
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  $WEEK8/code/tools/audit_p1_screen.py
python3 -m larb_week8.precalibrate

# Tests
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  -m unittest discover -s $WEEK8/code/tests -p 'test_*.py'
```

## GPU qualification (executed; 12 h request if resubmitted)

```sh
export LARB_ROOT=$ROOT
export LARB_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python
export LARB_ANALYSIS_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python
export LARB_MODEL_PATH=/storage/ice1/3/0/jwang3221/LARB-week5-env/model/Qwen3-4B
export LARB_WEEK8_ROOT=$WEEK8
export LARB_OUT=$WEEK8/results/p2a
sbatch $WEEK8/sbatch/p2a_qualify.sbatch
```

## What the GPU qualification found

The 24-item preview is the only scored GPU phase that ran, and it stopped the
line:

| arm | correct | accuracy | cap rate | missing box |
|---|---:|---:|---:|---:|
| fixed4k | 8/24 | 0.333 | 0.042 | 0.042 |
| fixed6k | 7/24 | 0.292 | 0.000 | 0.000 |
| fixed8k | 7/24 | 0.292 | 0.042 | 0.042 |

Gain 4k→8k **-4.2 points** against a +8.0 pass floor and a +4.0 near-miss
floor; 8k accuracy below the 0.35 band floor; answer change 62.5% and 8k
thinking median 8192, so the manipulation fired but did not move accuracy. The
verdict is robust to the grader (safe 8/7/7, loose 8/8/8, exact 8/7/7). The
frozen stop rule closed the calibration, refinement and live phases; the record
is `results/p2a/STOP.md`, `results/p2a/decision.json` and
`results/p2a/PREVIEW-24.md`.

The run also found and fixed three scaffolding defects that CPU checks could
not: two undefined code-path exports, a non-string environment value that
aborted the server spawn, and a forced-cue smoke that did not pin the frozen
rig (it ran with CUDA graphs on the first attempt). Details are in
[reports/P2A-QUALIFICATION-PLAN.md](reports/P2A-QUALIFICATION-PLAN.md) §4,
items 13-15, and each is locked by a unit test.

## Test suite (login node)

```sh
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  -m unittest discover -s week8/scaled-serving/code/tests -p 'test_*.py'
```

10 tests: preview pass/near-miss/stop, the safe grader, warm-up and band
handling, cut-after-close, the P2 plan, and the three runner-boundary defects.

## GPU qualification (executed 2026-11-16)

```sh
export LARB_ROOT=$ROOT
export LARB_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python
export LARB_ANALYSIS_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python
export LARB_MODEL_PATH=/storage/ice1/3/0/jwang3221/LARB-week5-env/model/Qwen3-4B
export LARB_WEEK8_ROOT=$WEEK8
export LARB_OUT=$WEEK8/results/p2a
sbatch $WEEK8/sbatch/p2a_qualify.sbatch
```

The job checks both environments, runs a forced-cue smoke, the 24-item
preview, the optional 48-item escalation, the 240 s calibration, the live
check, and then either writes a frozen P2 packet (`GO.md`) or a documented
stop (`STOP.md`). It never starts P2. No H100 was idle on 2026-11-16, so the
run used an existing 3 h interactive allocation (`7119809`) with the same
environment and the same stage layouts; the commands are in
[reports/P2A-QUALIFICATION-PLAN.md](reports/P2A-QUALIFICATION-PLAN.md) §3. The
sbatch file requests 12 h with an 11 h inner timeout so a full sequence can
absorb slow queue drain.

