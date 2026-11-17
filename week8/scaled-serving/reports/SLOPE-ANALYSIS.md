# Why the 4k→8k budget slope disappeared, and the next candidate pool

**Date:** 2026-11-16. **Status:** analysis complete; candidate preview done (see §5).
**Evidence:** every paired 4k/8k response measured in the frozen rig —
`week7/.../runs/slope` (216), `week7/.../runs/bridge` (120, 2 seeds) and
`week8/.../results/p2a/preview` (72) = **156 question-seed pairs**, graded with
the safe normalised rule. Script: `code/tools/analyze_slope_history.py`.

## 1. The question

Week 5 saved results and the P1 2023 AIME subset showed more accuracy at 8k
than at 4k (+8.3 points on 60 responses; +29.2 on 24 items). The last three
previews did not: the 2025-2026 main cohort (−8.3), HMMT Feb 2024 (+4.2) and
Omni-MATH hard (−4.2). Is that a rig problem, a pool problem, or noise?

## 2. What the records say

| family | pairs | 4k acc | 8k acc | gain | conversions | derailments | sign-test p | 4k answer cap | 4k answer tokens (median) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AIME (2023 + 2025) | 87 | 0.299 | 0.471 | **+0.172** | 18 | 3 | 0.0015 | 0.24 | 1417 |
| HMMT (Feb 2024 + 2025/26 preview) | 33 | 0.303 | 0.273 | -0.030 | 2 | 3 | 1.00 | 0.21 | 1270 |
| Omni-MATH hard | 24 | 0.333 | 0.292 | -0.042 | 1 | 2 | 1.00 | 0.04 | 1191 |
| CMIMC / SMT / Brumo | 12 | 0.250 | 0.250 | 0.000 | 0 | 0 | – | 0.33 | 1502 |
| **non-AIME pooled** | **69** | 0.304 | 0.275 | **-0.029** | 3 | 5 | 0.73 | 0.17 | 1224 |
| *all pairs* | *156* | *0.301* | *0.385* | *+0.083* | *21* | *8* | *0.024* | *0.21* | *1341* |

The AIME gain survives every obvious confound:

| AIME subset | pairs | 4k | 8k | gain | conv / derail | sign-test p |
|---|---:|---:|---:|---:|---|---:|
| all | 87 | 0.299 | 0.471 | +0.172 | 18 / 3 | 0.0015 |
| not 4k answer-capped | 66 | 0.394 | 0.561 | +0.167 | 14 / 3 | 0.013 |
| 4k answer-capped | 21 | 0.000 | 0.190 | +0.190 | 4 / 0 | 0.13 |
| 4k answer >1500 tokens | 38 | 0.079 | 0.263 | +0.184 | 7 / 0 | 0.016 |
| 4k answer ≤800 tokens | 12 | 0.667 | 0.833 | +0.167 | 2 / 0 | 0.50 |

## 3. Conclusions

1. **Not the rig.** The budget manipulation fires in every pool: the cue lands
   at exactly 4,096 / 6,096 / 8,192, thinking is truncated at the budget in
   92-100% of 4k and 80-92% of 8k responses, and the P1 bridge reproduced the
   week 5 reference within tolerance. Contract, cue and controller are unchanged.
2. **Not the answer cap.** AIME items whose 4k answer was *not* cut by the
   2,048-token allowance still gain +16.7 points. The cap explains at most the
   capped subgroup (4k accuracy is 0 by construction there).
3. **It is the family.** AIME-style multi-step integer problems carry the
   effect (+17.2 points, 18 conversions vs 3 derailments, p = 0.0015 on 87
   pairs); every non-AIME family measured in this rig is flat or negative
   (−2.9 points on 69 pairs). The recent previews drew from the flat families:
   Omni-MATH hard, HMMT, and a 2025-2026 cohort that is mostly
   HMMT/CMIMC/SMT/Brumo rather than AIME.
4. **Omni-MATH failed for a structural reason, not bad luck.** Its 4k answers
   are short (median 1,191 tokens) and almost never capped (4%); 62.5% of
   answers change between 4k and 8k but net conversions are −1. The model
   already "concludes" at 4k and spends the extra budget re-deriving the same
   wrong answer. AIME items instead keep deriving in the answer channel at 4k
   (median 1,417 tokens, 24% capped), so the budget is genuinely binding.
   The contingency table shows the same thing: when the answer changes, AIME
   converts 18 times and derails 3 times (ratio 6.0), non-AIME converts 3 and
   derails 5 (ratio 0.6); when the answer does not change, nothing moves in
   either family (0 conversions, 0 derailments). Answer churn without
   conversion is the signature of the flat families.

5. **Single 24-item previews are also noisy.** The rig's own power table gives
   a 24-item MDE of 16-21 points, so even a +17-point family effect will land
   near zero in some draws. Both effects — family and sampling — explain the
   run of flat results. The test is a family-level pool with ≥48 items, not a
   different threshold.
6. **The 24-item gate is biased, not merely noisy.** Re-measuring the same 24
   questions inside 48-item traces produced 0 of 48 identical token sequences
   and a +20.8 to +25.0-point gain instead of +8.3 (§5.3): with only 24
   requests in a 32-slot batch the answer channel runs longer, more 8k answers
   hit the 2,048-token allowance, and the 8k arm loses two to three responses.
   A second seed at 48 items reproduced the slope to within one response
   (+18.8 both times, §5.4). The week's flat results are therefore family
   effects plus a single-wave gate that systematically understates the 8k arm
   — not a change in the model or the rig.


## 4. Candidate pool and pre-declaration

`configs/pool_aime_2025_2026.json` (written before measurement) declares
**`aime-2025-2026-v1`**:

- **Sources:** AIME 2026 (30 items, `fresh`) + AIME 2025 (30 items, `exposed`,
  the same pool as the P1 bridge) from the frozen week 7 question set. All 60
  are integer-answer, self-gradable, context-safe and already inside the P0
  exclusion rules. No new data was fetched.
- **Selection:** 12 hash-ranked items per source in the 24-item preview, the
  next 12 per source in the 48-item escalation (24 more), 6 per source held as
  the reserve cohort. Salt `larb-week8-aime-candidate-v1`, seed base 900000.
- **Protocol:** identical to the qualified rig — legacy contract, eager, 32
  slots, threshold 8, one seed, 4k/6k/8k, 1.5 s spacing, 1,800 s deadline, and
  the frozen pass / near-miss / stop rule in `configs/qualify.json`.
- **Traces:** `artifacts/traces-candidates/gate-aime-preview{,48}.jsonl` with a
  hash manifest, plus `gate-aime-preview48-s2.jsonl` for the second-seed
  replicate (seed base 910000); raw records in `results/p2b/`.

## 5. Result

### 5.1 Pre-registered 24-item gate

| arm | correct | accuracy | cap rate | missing box | thinking median |
|---|---:|---:|---:|---:|---:|
| fixed4k | 8/24 | 0.333 | 0.292 | 0.292 | 4096 |
| fixed6k | 8/24 | 0.333 | 0.250 | 0.250 | 6096 |
| fixed8k | 10/24 | 0.417 | 0.208 | 0.208 | 8192 |

Paired 4k vs 8k: 8k better on 2 items, 4k better on 0, both 8, neither 14;
gain **+8.3 points**, answer change 45.8%, discordance 8.3%, sign test p = 0.50.

Decision: **`inconclusive_grader`** — the 8k missing-box rate (20.8%) is above
the pre-registered 20% ceiling, which `configs/qualify.json` defines as a stop,
not a pool failure. The gain is at the +8.0-point pass floor and the 8k
accuracy is inside the 0.35-0.75 band, but the measurement is not admissible.

**Cause.** All five 8k missing-box records are `answer_cap` records: 2,049
answer tokens after an 8,192-token cue, i.e. the model was still deriving when
the legacy 2,048-token answer allowance ran out. The same items are capped at
4k (7/24) and 6k (6/24). The window is the binding constraint: the server
reserves `8,192 + 14 + 2,048 + 2 = 10,256` tokens, leaving about 2,032 for the
prompt inside 12,288, and a 4,096-token answer allowance cannot be reserved at
all (12,304 > 12,288 before any prompt). The legacy contract therefore cannot
give these items more answer room at 8k; the capped responses stay in the
denominator and are graded wrong.

**Reading.** The family direction is confirmed on fresh 2026 items (+8.3
points, 41.7% at 8k, no derailments, the closest arm ordering seen in any
preview), but AIME 2025+2026 as currently filtered does not clear the grader
gate: roughly one in five 8k responses runs out of answer space. Passing needs
either a pool-level filter on derivation length or a contract that rebalances
thinking against answer tokens inside the same window; neither may be adopted
after seeing this outcome, so both are next-cycle decisions. §5.3 shows that
this particular verdict is also a property of the single-wave trace: the same
questions in a two-wave trace keep the 8k arm out of the cap in all but 2-3
responses.

### 5.2 Exploratory 48-item measurement (descriptive, not a gate)

The 48-item set (the preview 24 plus the 24 escalation items) was measured in
the same allocation to size the cap rate at larger n. It is labelled
exploratory because `configs/qualify.json` triggers the escalation only after a
near-miss and this preview was a stop; **it cannot authorise P2 and does not
change §5.1.**

| arm | correct | accuracy | 95% CI | cap rate | missing box |
|---|---:|---:|---|---:|---:|
| fixed4k | 18/48 | 0.375 | [0.252, 0.516] | 0.167 | 0.125 |
| fixed6k | 22/48 | 0.458 | [0.326, 0.597] | 0.083 | 0.083 |
| fixed8k | 27/48 | 0.562 | [0.423, 0.693] | 0.062 | 0.062 |

Paired 4k vs 8k: 11 conversions, 2 derailments, gain **+18.8 points**, answer
change 64.6%, sign test p = 0.022. Applied to this set the frozen rule returns
`pass` (gain ≥ 8, accuracy in band, 8k cap 6.2% ≤ 20%, change ≥ 10%). Because
of when it was run, that is evidence, not authorisation. A second seed
reproduced it exactly (§5.4).

### 5.3 The 24-item trace is not a 24-question subset of a 48-item trace

The 48-item runs re-measured the 24 preview questions with the same seeds; only
the trace (and so the batch composition) differed.

| run | 4k correct | 4k caps | 8k correct | 8k caps | 4k→8k gain |
|---|---:|---:|---:|---:|---:|
| 24-item trace (one wave) | 8/24 | 7 | 10/24 | 5 | +8.3 |
| 48-item trace, seed 900000 | 6/24 | 4 | 12/24 | 2 | +25.0 |
| 48-item trace, seed 910000 | 8/24 | 7 | 13/24 | 2 | +20.8 |

**0 of 48** re-measured token sequences were identical to the 24-item run (for
example `aime2026-012` at 8k generated 10,218 versus 9,875 tokens). Batched
decoding in this rig is not reproducible across batch composition, and the
effect is systematic rather than random: when only 24 requests share a 32-slot
batch, the answer channel runs longer and five 8k answers hit the 2,048-token
allowance instead of two, which costs the 8k arm two to three responses. The
single-wave 24-item gate therefore *understates* the 8k arm by 12-17 points on
these questions.

This is a measurement-design defect, not a property of the pool: the same 24
questions carry a real +20 to +25-point slope that a 24-item gate reports as
+8.3. The gate must be run on a trace with at least two admission waves (48
requests on 32 slots) so both arms see comparable batching.

### 5.4 Second-seed replicate at 48 items

Same 48 questions, seed base 910000 (the gate uses 900000), identical protocol:

| arm | seed 900000 | seed 910000 | combined (96 responses) |
|---|---:|---:|---:|
| fixed4k | 18/48 (0.375) | 17/48 (0.354) | 35/96 (0.365) |
| fixed6k | 22/48 (0.458) | 22/48 (0.458) | 44/96 (0.458) |
| fixed8k | 27/48 (0.562) | 26/48 (0.542) | 53/96 (0.552) |
| 4k→8k gain | +18.8 | +18.8 | **+18.8** |
| conversions / derailments | 11 / 2 | 11 / 2 | **22 / 4** |
| sign-test p | 0.022 | 0.022 | **5.3e-4** |

The two seeds agree to one response per arm. Seed variance is small; the
instability in §5.3 is batch composition, which is controllable. By the frozen
rule both runs would pass (gain 18.8, 8k accuracy 0.54-0.56, 8k caps 6-8%,
answer change 58-65%); they remain evidence, not authorisation, because the
gate run itself returned `inconclusive`.




## 6. Reproduction

```sh
export PYTHONPATH=week8/scaled-serving/code:week7/scaled-serving/code
/storage/ice1/3/0/jwang3221/LARB-week5-env/analysis-venv/bin/python \
  week8/scaled-serving/code/tools/analyze_slope_history.py
```

It re-pairs every fixed4k/fixed8k record by (condition, question, seed), grades
with `larb_week8.audit.grade_record(..., "normalized_safe")` and prints the
tables above. The candidate pool is built by
`code/tools/build_candidate_pool.py` and previewed by
`code/tools/run_candidate_preview.py` (`sbatch/p2b_candidate_preview.sh`).

