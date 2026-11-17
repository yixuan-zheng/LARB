# P2A status: the GPU preview stopped the Omni-MATH pool

**Date:** 2026-11-16 (GPU run, America/New_York; records are UTC 2026-11-17).
**Decision:** **STOP.** P2 remains withheld.
**Records:** `results/p2a/STOP.md`, `results/p2a/decision.json`,
`results/p2a/preview-24.json`, `results/p2a/PREVIEW-24.md`,
`results/p2a/smoke/smoke.json`.
**GPU used:** one H100 80 GB on `ice-gpu` (Slurm interactive allocation
`7119809`, 3 h): forced-cue smoke 4 min, 24-item preview 8 min. Everything else
in this folder is CPU-only.

## The gate result

The 24-item Omni-MATH preview (`omni-math-hard-v1`, one seed, 4k/6k/8k, eager,
legacy contract, 32 slots, 1,800 s phase deadline) **fails the pre-registered
AND rule**:

| arm | correct | accuracy | 95% CI | cap rate | missing box | thinking median | cue position |
|---|---:|---:|---|---:|---:|---:|---:|
| fixed4k | 8/24 | 0.333 | [0.180, 0.533] | 0.042 | 0.042 | 4096 | 4096 (24/24) |
| fixed6k | 7/24 | 0.292 | [0.149, 0.492] | 0.000 | 0.000 | 6096 | 6096 (24/24) |
| fixed8k | 7/24 | 0.292 | [0.149, 0.492] | 0.042 | 0.042 | 8192 | 8192 (22/24) |

Paired 4k vs 8k: 8k better on 1 item, 4k better on 2, both 6, neither 15. Gain
**-4.2 points**, answer change 62.5%, discordance 12.5%, sign test p = 1.00.

| criterion (frozen) | required | measured | verdict |
|---|---|---|---|
| 4k→8k gain | ≥ +8.0 points | **-4.2** | fail |
| near-miss gain floor | ≥ +4.0 points | -4.2 | stop, not near-miss |
| 8k accuracy | 0.35-0.75 | **0.292** | fail |
| 8k cap rate | ≤ 0.20 | 0.042 | pass |
| 8k thinking median | ≤ 8192 | 8192 | pass |
| coverage / grader | complete, missing box ≤ 0.20 | 72/72, 0.042 | pass |

The result is not a grading artefact. Re-graded on the same records, the
4k/6k/8k counts are 8/7/7 (safe), 8/8/8 (loose Math-Verify), 8/7/7 (exact
normalised) and 10/8/9 (raw, inadmissible). Under every admissible grader the
8k arm is at or below 4k, and only the raw grader lifts 8k accuracy above the
35% floor. The mismatches are wrong answers (for example `114` where the
reference is `262`), not equivalent forms the safe rule rejected.

**Mechanism.** The budget manipulation fires as designed — the cue lands
exactly at 4,096 / 6,096 / 8,192 and the median response grows 5,300 → 7,133 →
9,096 tokens — and 62.5% of extracted answers change, but accuracy is flat
(33.3% → 29.2% → 29.2%). On this pool more thinking tokens do not buy
correctness, so the pool cannot carry a serving comparison at any budget.

## Consequences

| Phase | Status |
|---|---|
| Transition checks (serving and analysis) | pass, 57 and 58 checks, 0 failures |
| Forced-cue smoke | pass, cue at exactly 64 tokens, 64-token budget and cap |
| 24-item preview | **stop** |
| 48-item escalation | not triggered (the decision is a stop, not a near-miss) |
| 240 s calibration, refinement, live check | **not run**: the frozen stop rule in `configs/qualify.json` forbids calibrating after a stop |
| P2 freeze | not written; `configs/p2_main_frozen.json` does not exist |

The remaining allocation time was left unused rather than spent on phases the
pre-declared rule excludes.

## What is settled

| Question | Answer | Evidence |
|---|---|---|
| Does the 2023 AIME intersection carry a 4k→8k slope? | Yes: 6/24 → 13/24, +29.2 points, 70.8% answer change. | `P1-SCREEN-AUDIT.md` |
| Is it a usable main pool? | No: 25 items at 4 seeds give a 16-21 point MDE. Witness only. | `P1-SCREEN-AUDIT.md` |
| Does the pre-declared fallback (Omni-MATH hard) carry the slope? | **No.** -4.2 points, 29.2% at 8k, no budget response. | `results/p2a/PREVIEW-24.md` |
| Is the rig innocent? | Yes: 72/72 scored, 0 request errors, injection lag ≤ 2.6 ms, exact cue positions, `enforce_eager=True` in the server log, cap and coverage checks pass. | `results/p2a/preview/`, `logs/` |
| Is the 240 s calibration or live check validated on GPU? | No. They have still never run; they are untested gates for any future pool. | this folder |

## Follow-up in the same allocation: why the slope vanished, and the next pool

[SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md) re-analyses every paired 4k/8k response
measured in this rig (156 question-seed pairs). The answer is family, not rig:
AIME gains **+17.2 points** (18 conversions vs 3 derailments, sign test
p = 0.0015) while every non-AIME family is flat or negative (**-2.9 points**,
3 vs 5, p = 0.73). The cue, truncation and grader behave identically in both
groups, and the AIME gain survives removing answer-capped items (+16.7). The
recent previews drew from the flat families — Omni-MATH hard, HMMT, and a
2025-2026 cohort that is mostly HMMT/CMIMC/SMT/Brumo.

Candidate **`aime-2025-2026-v1`** (AIME 2026, fresh, plus AIME 2025; 60 items,
pre-declared in `configs/pool_aime_2025_2026.json` before measurement) was
previewed in the same allocation:

| arm | correct | accuracy | cap rate | missing box |
|---|---:|---:|---:|---:|
| fixed4k | 8/24 | 0.333 | 0.292 | 0.292 |
| fixed6k | 8/24 | 0.333 | 0.250 | 0.250 |
| fixed8k | 10/24 | 0.417 | 0.208 | 0.208 |

Gain **+8.3 points**, answer change 45.8%, no derailments — the direction and
the arm ordering the family analysis predicted — but the 8k missing-box rate
(20.8%) is over the pre-registered 20% ceiling, so the decision is
**`inconclusive_grader`, a documented stop**. Every missing box is an
answer-cap record: 2,049 answer tokens after an 8,192-token cue. The 12,288
window reserves 10,256 tokens for an 8k request, so a 4,096-token answer
allowance cannot be reserved at all; the legacy contract, not the pool,
blocks this candidate.

**Consequence for the next cycle:** passing this family needs either a
pool-level filter on derivation length or a contract that rebalances thinking
against answer space inside the same window. Both are pre-measurement design
decisions and neither is adopted here.

### The larger sets, a second seed and the gate design

The same allocation then measured the 48-item set twice: the escalation set
with the gate seed (900000) and with a second seed (910000).

| arm | seed 900000 | seed 910000 | combined |
|---|---:|---:|---:|
| fixed4k | 18/48 | 17/48 | 35/96 (0.365) |
| fixed6k | 22/48 | 22/48 | 44/96 (0.458) |
| fixed8k | 27/48 | 26/48 | 53/96 (0.552) |
| 4k→8k gain | +18.8 | +18.8 | **+18.8** (22 conversions, 4 derailments, p = 5.3e-4) |

Both runs would pass the frozen rule (8k caps 6-8%, answer change 58-65%);
they are labelled exploratory because the escalation is pre-declared only for a
near-miss and the gate run itself returned `inconclusive`. Seed variance is
small: the two seeds agree to one response per arm.

The re-measurement also localised the gate defect. The same 24 preview
questions, with the same seeds, scored differently inside the 48-item traces:
**0 of 48 token sequences were identical**, and their 4k→8k gain was +20.8 to
+25.0 points instead of +8.3. With only 24 requests in a 32-slot batch the
answer channel runs longer, five 8k answers hit the 2,048-token allowance
instead of two, and the 8k arm loses two to three responses. A single-wave
24-item trace therefore *understates* the 8k arm by 12-17 points on this pool;
that is a measurement-design defect, not a property of the candidate.




## Open, and the next action

The Omni-MATH pool is closed by its own stop. The AIME-family candidate is
viable (+18.8 points on 48 items, p = 0.022) but is not yet authorised, because
its 24-item gate run returned `inconclusive`. Three pre-measurement decisions
are needed before another preview:

1. **Gate design.** Run the gate on a trace with at least two admission waves
   (48 requests on 32 slots) and two seeds (96 responses). A single-wave
   24-item trace systematically understates the 8k arm: it changes the answer
   channel, pushes five rather than two 8k answers into the 2,048-token
   allowance, and reports +8.3 points where the same questions give +20.8 to
   +25.0 (§5.3 of [SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md)). Seed variance is
   small (+18.8 on both seeds at 48 items), so trace shape matters more than
   seed count.
2. **Answer space.** Answer caps persist on a few long-derivation items (3 of
   48 at 8k, 8 of 48 at 4k). Either filter the pool on derivation length or
   pre-declare a contract that reserves more answer room by lowering the 8k
   thinking budget; the 12,288 window cannot reserve a 4,096-token answer
   allowance.

3. **Then** calibrate the 240 s band and run the live check at the chosen rate;
   the rig itself does not need re-qualification.

A documented stop remains a valid outcome, and nothing here is authorised to
change the preview thresholds, pool filters, deadline or cut rule in response
to the outcomes above.



## Non-negotiable limits

- Every Omni-MATH item is `exposed`; this is a serving-policy test on a public
  benchmark, not fresh-data evidence.
- One model (Qwen3-4B), one H100, one block; no 3-point claim.
- A 24-item, one-seed preview resolves only a large slope. The stop means "this
  pool does not show the slope", not "the hypothesis is false".
