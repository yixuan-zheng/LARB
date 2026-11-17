# P2A qualification runbook: preview, 240 s calibration, live check

**Status: executed on GPU 2026-11-16 and stopped at the 24-item preview.**
The Omni-MATH preview showed no 4k→8k slope (8/24 at 4k, 7/24 at 8k, -4.2
points; 8k accuracy 29.2%), so the frozen stop rule closed the sequence before
calibration. P2 is not authorised and `configs/p2_main_frozen.json` does not
exist. The outcome is recorded in `reports/P2A-STATUS.md`,
`results/p2a/STOP.md` and `results/p2a/decision.json`.

**Purpose (unchanged):** decide whether a pre-declared pool can carry a
credible serving comparison, and freeze P2 only if the preview, the 240 s
calibration and the live manipulation check all pass.

## 1. Inputs (built on CPU before the GPU run)

| Artifact | What it is |
|---|---|
| `configs/pool_omni.json` | Pre-declared fallback pool, filters, strata, source cap, seed base |
| `data/processed/questions.jsonl` | 240 selected Omni-MATH signal questions, built without a model |
| `artifacts/cohort.json` | 216 main / 24 preview / 24 escalation / 192 main-after-escalation / 48 calibration / 92 filler |
| `artifacts/traces/gate-omni-preview.jsonl` | 24-item, one-seed preview trace |
| `artifacts/traces/gate-omni-preview48.jsonl` | 48-item near-miss escalation trace |
| `artifacts/traces/gate-omni-cal-*.jsonl` | 25-minute calibration traces at 600-1200/h |
| `configs/qualify.json` | Frozen preview, calibration and live-check rules |
| `configs/p2_main_draft.json` | Withheld P2 template; never runnable as-is |
| `reports/P1-SCREEN-AUDIT.md` | 2023 AIME / HMMT 2024 split and grading audit |
| `reports/POOL-DECISION.md` | Why Omni-MATH, why 240 s, what would stop the line |
| `reports/PRECALIBRATION-240.md` | CPU queue simulation and the rate-grid rationale |

## 2. Job order

The GPU job runs the following sequence and stops at the first failure.
The week 7 protocol file remains frozen at 180 s for the P1 evidence; the
Week 8 traces and phases carry the 240 s SLO explicitly, and the frozen P2
packet is the authoritative Week 8 deadline.

Executed on 2026-11-16: steps 1-3. Steps 4-8 were **closed by the stop rule**,
not skipped for time. Per-step status is in `reports/P2A-STATUS.md`.

A later candidate run in the same allocation (`aime-2025-2026-v1`) used the
same phases and thresholds through `code/tools/run_candidate_preview.py`
(`sbatch/p2b_candidate_preview.sh`); its analysis and outcome are in
[SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md). It does not change this runbook's
sequence or thresholds.

1. **Transition check, serving venv.** Exact chat-template context, trace
   validation, source lock, dry-run plans and sbatch syntax. The analysis venv
   separately checks Math-Verify and the safe grading rule.
2. **GPU smoke.** One forced-cue request (`LARB_FORCE_BUDGET=64`,
   `LARB_FORCE_ANSWER_CAP=64`) validates the server wrapper, the Omni-MATH
   question set, exactly one cue, the cap flag and clean shutdown.
3. **24-item preview.** 4k/6k/8k, one seed, legacy contract, eager, 32 slots.
   The pre-registered AND rule decides pass / near-miss / stop. Incomplete
   coverage or a missing-box rate above 20% is `inconclusive_*` and is treated
   as a stop, not a pool failure.
4. **48-item escalation, only on near-miss.** The original 24 plus 24
   hash-ranked main items. A pass here removes those 24 from main.
5. **240 s calibration.** fixed8k, 48 main-cohort questions, 30% filler,
   25 minutes per rate (10-minute warm-up, 15-minute measured window), coarse
   grid at 600-1200/h. Pressure is reported at waiting ≥8; timeliness is
   measured from actual client submission.
6. **One refinement round, only if no rate is in the 15-40% band.** Three
   25-minute points between the highest sub-band and lowest over-band rate.
7. **Live check at the chosen rate.** 25 minutes, live arm, same trace mix.
   Requires at least one in-flight cut, pressure at waiting ≥8, no cut after
   close, and both 4096 and 8192 admissions.
8. **Freeze or stop.** A passing sequence writes
   `configs/p2_main_frozen.json`, builds the main traces and writes `GO.md`.
   Any failure writes `STOP.md` and `decision.json`; the job exits zero because
   a documented stop is a valid outcome. The frozen packet chooses the largest
   pre-declared seed count (4, then 3, then 2) whose estimated arrival span
   plus the low control fits 13.5 h at a 1.10 overhead factor; if none fits,
   the result is a documented stop/split, not an overrun.

## 3. Commands

### CPU-side reproduction (login node)

```sh
export ROOT=/home/hice1/jwang3221/scratch/LARB
export WEEK8=$ROOT/week8/scaled-serving
export PYTHONPATH=$WEEK8/code:$ROOT/week7/scaled-serving/code

# Rebuild the pool and the traces (idempotent; refuses a moved source hash)
/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python \
  $WEEK8/code/tools/build_omni_pool.py
/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python \
  $WEEK8/code/tools/build_traces.py --stage all

# Audit the P1 records (analysis venv has Math-Verify)
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  $WEEK8/code/tools/audit_p1_screen.py

# CPU pre-calibration
python3 -m larb_week8.precalibrate

# Unit tests (analysis venv runs all seven; serving venv skips the Math-Verify case)
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  -m unittest discover -s $WEEK8/code/tests -p 'test_*.py'
```

### GPU submission

```sh
export LARB_ROOT=$ROOT
export LARB_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/venv/bin/python
export LARB_ANALYSIS_PYTHON=/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python
export LARB_MODEL_PATH=/storage/ice1/3/0/jwang3221/LARB-week5-env/model/Qwen3-4B
export LARB_WEEK8_ROOT=$WEEK8
export LARB_OUT=$WEEK8/results/p2a

cd $ROOT && sbatch $WEEK8/sbatch/p2a_qualify.sbatch
```

The script does not submit itself. It checks the two environments before the
`srun` allocation and never starts P2. Use a fresh `LARB_OUT` for each attempt;
the runner refuses an output directory that already has preview/calibration
phases, so archive a failed attempt rather than appending to it. The transition
check also refuses to overwrite an existing `configs/p2_main_frozen.json`; to
requalify, archive the frozen packet first. P2 has its own script,
`sbatch/p2_main.sbatch`, which refuses to run unless
`configs/p2_main_frozen.json` exists.

**Allocation and execution as run (2026-11-16).** No H100 was idle in
`ice-gpu` (`sbatch --test-only` projected a start about two days out), so the
sequence ran inside an existing 3 h interactive allocation (`7119809`) with the
same environment, one stage at a time:

```sh
srun --jobid=7119809 --overlap bash $WEEK8/sbatch/p2a_inallocation_preview.sh  # smoke, preview
srun --jobid=7119809 --overlap bash $WEEK8/sbatch/p2a_inallocation_smoke.sh    # smoke on the fixed code
```

`--stage smoke` and `--stage preview` write the same layouts as `run_all`
(`smoke/`, `preview/`), so the records are directly comparable with a full
sequence. Because the preview returned a stop, the calibration stage was not
run and the decision record was written with the same helper `run_all` uses
(`decision.write_decision(..., go=False, preview)`), which produced
`results/p2a/STOP.md` and `results/p2a/decision.json`.

The sbatch file now requests 12 h with an 11 h inner timeout (was 10 h / 9 h) so
that a full sequence — 13 coarse rates, one refinement round and the live check
— can absorb slow queue drain without being killed before it writes its
decision. The wall clock is an operational budget, not a measurement
parameter.


## 4. Transition risks found and handled

The P1 job found eleven scaffolding defects only by running the GPU. This
package adds CPU checks and small design changes so the next transition does
not repeat them. The review found these additional issues:

1. **The real context limit is not the P0 exclusion limit.** The server
   reserves `8,192 + 14 + 2,048 + 2 = 10,256` tokens for a signal request, so a
   12,288-token window leaves 2,032 prompt tokens. The P0 exclusion rule was
   3,900, which would have produced HTTP 400s on any long Omni-MATH prompt.
   The pool is filtered at 1,850 local tokens; the Omni-MATH exact
   chat-template maximum is 324 tokens (1,708-token margin), and the merged
   week 7 filler maximum is 743 tokens (1,289-token margin). The transition
   check verifies the merged set.
2. **Math-Verify 0.9.0 is not safe for all expressions.** It cannot parse
   `\dfrac` references (five HMMT 2024 false negatives) and it parses two
   different radical expressions as the same integer (one cmimc 2025 false
   positive). The preview uses exact normalised match first and Math-Verify
   only when the parse is not lossy; a unit test locks the known cases.
3. **The P1 slope pass rule used OR.** The pre-registered rule is gain ≥8
   points AND answer change ≥10%. The audit reports both and applies AND.
4. **The P1 calibration pressure fraction used threshold 4, not 8.** At 931/h
   the corrected pressure fraction is 0.566, not 0.650. The calibration
   reports both, and the live check uses 8.
5. **The P1 20-minute points were below steady state.** The Week 8 calibration
   uses a 10-minute warm-up and scores only the last 15 minutes; the queue is
   not reset between the two windows.
6. **Timeliness was measured from the scheduled trace offset.** The client now
   uses actual submission time for latency and misses; with sub-second
   injection lag the difference is small, but it is no longer conceptually
   wrong.
7. **Appending live phases could overwrite `phases.json`.** The Week 8 runner
   preserves existing phases when a second sequence writes to the same run
   directory.
8. **The frozen week 7 server cannot load Omni-MATH questions.** A thin
   `larb_week8.server_entry` replaces `load_questions` before `main()`; the
   frozen week 7 code and its source lock are untouched.
9. **The source-lock path convention differed.** P1 hashes are week-7-relative;
   the check now uses the same convention and fails if any frozen file moves.
10. **P2 could be frozen without all three gates.** The runner writes the P2
    packet only after preview, calibration and live check all pass; otherwise
    it writes a stop record.
11. **No forced-cue smoke on the week 7 path.** The Week 8 job starts with a
    forced 64-token cue and a 64-token cap, so an engine/controller mismatch
    fails in minutes rather than after a phase.
12. **Calibration can look like a band by accident.** The analysis reports the
    raw bracket, the warm-up window, pressure at both thresholds and the
    pre-declared refinement; a single in-band point is not adjusted after
    seeing the main outcome.

Three further defects were found by the GPU run itself (2026-11-16) and fixed
before the preview; each is now locked by a unit test:

13. **`config.WEEK8_CODE` / `config.WEEK7_CODE` were undefined.** The runner's
    server and analysis environments referenced them but `larb_week8/config.py`
    only imported `REPO_ROOT`, `WEEK7_ROOT` and `WEEK8_ROOT`, so the very first
    `srun` step died with `AttributeError` before starting the engine.
14. **Non-string environment values killed the server spawn.** The smoke passed
    integer `LARB_FORCE_BUDGET` / `LARB_FORCE_ANSWER_CAP` values straight into
    `os.environ`, raising `TypeError: expected str ... not int`. `runner.server_env`
    now coerces every value to `str`.
15. **The forced-cue smoke did not pin the frozen rig.** It inherited the
    server defaults, which are `enforce_eager=0`, so the first smoke ran with
    CUDA graphs and compilation (that `server.log` is archived locally as
    `logs/smoke-first-attempt-graphs.log`). `SMOKE_ENV` now pins legacy, eager,
    32 slots and threshold 8 — the same settings a scored phase uses — and the
    corrected smoke passed with `enforce_eager=True` in the engine config.

The preview itself confirmed the rig on the eager path: 72/72 requests scored,
0 request errors, maximum injection lag 2.6 ms, cues at exactly 4,096 / 6,096 /
8,192.

## 5. Outputs and pass/fail records

| Output | Meaning | Status 2026-11-16 |
|---|---|---|
| `results/p2a/transition-serving.json` | Exact context, trace and source-lock checks | pass (57 checks) |
| `results/p2a/transition-analysis.json` | Math-Verify, pool and dry-run checks | pass (58 checks) |
| `results/p2a/smoke/smoke.json` | Forced-cue smoke result | pass (frozen rig) |
| `results/p2a/preview-24.json`, `PREVIEW-24.md` | 24-item decision | **stop** |
| `results/p2a/preview-48.json`, `PREVIEW-48.md` | 48-item escalation, if used | not triggered |
| `results/p2a/calibration.json`, `CALIBRATION.md` | Rate curve, chosen rate, live check | not run (stop rule) |
| `results/p2a/decision.json`, `STOP.md` | Final go/no-go record | written, `go=false` |
| `configs/p2_main_frozen.json` | Only on GO; P2 runnable | absent |
| `artifacts/source-lock-p2a.json` | Week 8 code/config/artifact hashes and the week 7 lock | written |

The raw run records sit in `results/p2a/preview/` (`requests/`,
`request-state/`, `scheduler.jsonl`, `worker.jsonl`, `clients/`, `phases.json`)
and `results/p2a/smoke/`.

## 6. What this package deliberately does not do

- It does not run P2, and it does not change any frozen week 7 file.
- It does not integrate the parallel prediction work or the question-level
  allocation replay; that is a separate thread.
- It does not tune the pool, deadline, pressure threshold or cut rule after an
  outcome. The only post-outcome decision is pass / near-miss / stop, exactly
  as pre-declared in `configs/qualify.json`.
