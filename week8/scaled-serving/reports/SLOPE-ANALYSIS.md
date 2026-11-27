# Why the 4k→8k budget slope is family-dependent

**Status:** analysis complete (2026-11-16). This is the basis for the AIME
2025+2026 preview authorisation in
[P2B-CALIBRATION-STOP.md](P2B-CALIBRATION-STOP.md). Evidence: every paired 4k/8k
response measured in the frozen rig — `week7/.../runs/slope` (216),
`week7/.../runs/bridge` (120, 2 seeds) and `week8/.../results/p2a/preview`
(72) = **156 question-seed pairs**, graded with the safe normalised rule.
Script: `code/tools/analyze_slope_history.py`.

## 1. The question

Week 5 saved results and the P1 2023 AIME subset showed more accuracy at 8k than
at 4k (+8.3 points on 60 responses; +29.2 on 24 items). Three later previews did
not: the 2025–2026 main cohort (−8.3), HMMT Feb 2024 (+4.2) and Omni-MATH hard
(−4.2). Is that a rig problem, a pool problem, or noise?

## 2. What the records say

| family | pairs | 4k acc | 8k acc | gain | conversions | derailments | sign-test p |
|---|---:|---:|---:|---:|---:|---:|---:|
| AIME (2023 + 2025) | 87 | 0.299 | 0.471 | **+0.172** | 18 | 3 | 0.0015 |
| HMMT (Feb 2024 + 2025/26 preview) | 33 | 0.303 | 0.273 | −0.030 | 2 | 3 | 1.00 |
| Omni-MATH hard | 24 | 0.333 | 0.292 | −0.042 | 1 | 2 | 1.00 |
| CMIMC / SMT / Brumo | 12 | 0.250 | 0.250 | 0.000 | 0 | 0 | – |
| **non-AIME pooled** | **69** | 0.304 | 0.275 | **−0.029** | 3 | 5 | 0.73 |
| *all pairs* | *156* | *0.301* | *0.385* | *+0.083* | *21* | *8* | *0.024* |

The AIME gain survives every obvious confound:

| AIME subset | pairs | 4k | 8k | gain | conv / derail |
|---|---:|---:|---:|---:|---|
| all | 87 | 0.299 | 0.471 | +0.172 | 18 / 3 |
| not 4k answer-capped | 66 | 0.394 | 0.561 | +0.167 | 14 / 3 |
| 4k answer >1500 tokens | 38 | 0.079 | 0.263 | +0.184 | 7 / 0 |
| 4k answer ≤800 tokens | 12 | 0.667 | 0.833 | +0.167 | 2 / 0 |

## 3. Conclusions

1. **Not the rig.** The budget manipulation fires in every pool: the cue lands at
   exactly 4,096 / 6,096 / 8,192, thinking is truncated at the budget in 92–100%
   of 4k and 80–92% of 8k responses, and the P1 bridge reproduced the week 5
   reference within tolerance.
2. **Not the answer cap.** AIME items whose 4k answer was *not* cut by the
   2,048-token allowance still gain +16.7 points.
3. **It is the family.** AIME-style multi-step integer problems carry the effect
   (+17.2 points, 18 conversions vs 3 derailments, p = 0.0015); every non-AIME
   family measured in this rig is flat or negative (−2.9 points on 69 pairs).
4. **Omni-MATH failed for a structural reason.** Its 4k answers are short
   (median 1,191 tokens) and almost never capped (4%); 62.5% of answers change
   between 4k and 8k but net conversions are −1. The model already "concludes"
   at 4k and spends the extra budget re-deriving the same wrong answer. AIME
   items keep deriving in the answer channel at 4k (median 1,417 tokens, 24%
   capped), so the budget is genuinely binding.
5. **Single 24-item previews are noisy and biased.** A 24-item MDE is 16–21
   points, so a +17-point family effect can land near zero. Re-measuring the same
   24 questions inside 48-item traces produced 0 of 48 identical token sequences
   and a +20.8 to +25.0-point gain instead of +8.3: with only 24 requests in a
   32-slot batch the answer channel runs longer, more 8k answers hit the
   2,048-token allowance, and the 8k arm loses responses. The gate must use at
   least two admission waves.

All records are graded with the safe normalised rule. Against raw Math-Verify it
fixes 5 false negatives (all HMMT Feb 2024) and rejects 1 loose false positive
(CMIMC 2025); the prompt check found 0 issues across 216 records.

## 4. Candidate pool and pre-declaration

`configs/pool_aime_2025_2026.json` (written before measurement) declares
**`aime-2025-2026-v1`**:

- **Sources:** AIME 2026 (30 items, `fresh`) + AIME 2025 (30 items, `exposed`,
  the same pool as the P1 bridge) from the frozen week 7 question set. All 60
  are integer-answer, self-gradable, context-safe and inside the P0 exclusion
  rules.
- **Selection:** 12 hash-ranked items per source in the 24-item preview, the
  next 12 per source in the 48-item escalation, 6 per source held as the reserve
  cohort. Salt `larb-week8-aime-candidate-v1`, seed base 900000.
- **Protocol:** legacy contract, eager, 32 slots, threshold 8, 4k/6k/8k, and the
  frozen pass / near-miss / stop rule in `configs/qualify.json`.
- **Traces:** `artifacts/traces-candidates/gate-aime-preview{,48}.jsonl` with a
  hash manifest, plus `gate-aime-preview48-s2.jsonl` for the second-seed
  replicate.

## 5. Result

### 5.1 Pre-registered 24-item gate

| arm | correct | accuracy | cap rate | missing box |
|---|---:|---:|---:|---:|
| fixed4k | 8/24 | 33.3% | 29.2% | 29.2% |
| fixed6k | 8/24 | 33.3% | 25.0% | 25.0% |
| fixed8k | 10/24 | 41.7% | 20.8% | 20.8% |

Paired 4k vs 8k: gain **+8.3 points**, answer change 45.8%, sign-test p = 0.50.
Decision: **`inconclusive_grader`** — the 8k missing-box rate (20.8%) is above
the pre-registered 20% ceiling. All five 8k missing-box records are `answer_cap`
records. The window is the binding constraint: an 8k request reserves
10,256 tokens, leaving about 2,032 for the prompt inside 12,288, so the legacy
contract cannot give these items more answer room without a pool filter or a
contract change. Neither was adopted after seeing the result.

### 5.2 Exploratory 48-item measurement

| arm | correct | accuracy | cap rate |
|---|---:|---:|---:|
| fixed4k | 18/48 | 37.5% | 16.7% |
| fixed6k | 22/48 | 45.8% | 8.3% |
| fixed8k | 27/48 | 56.2% | 6.2% |

Paired 4k vs 8k: 11 conversions, 2 derailments, gain **+18.8 points**, sign-test
p = 0.022. The frozen rule returns `pass`, but because the escalation was run
after a stop this is evidence, not authorisation.

### 5.3 The 24-item trace is not a 24-question subset of a 48-item trace

| run | 4k correct | 4k caps | 8k correct | 8k caps | 4k→8k gain |
|---|---:|---:|---:|---:|---:|
| 24-item trace (one wave) | 8/24 | 7 | 10/24 | 5 | +8.3 |
| 48-item trace, seed 900000 | 6/24 | 4 | 12/24 | 2 | +25.0 |
| 48-item trace, seed 910000 | 8/24 | 7 | 13/24 | 2 | +20.8 |

**0 of 48** re-measured token sequences were identical to the 24-item run.
Batched decoding in this rig is not reproducible across batch composition, and
the effect is systematic: fewer requests per batch lengthens the answer channel
and costs the 8k arm responses. The single-wave 24-item gate therefore
*understates* the 8k arm by 12–17 points. This is a measurement-design defect,
not a pool property.

### 5.4 Second-seed replicate at 48 items

| arm | seed 900000 | seed 910000 | combined (96 responses) |
|---|---:|---:|---:|
| fixed4k | 18/48 (37.5%) | 17/48 (35.4%) | 35/96 (36.5%) |
| fixed6k | 22/48 (45.8%) | 22/48 (45.8%) | 44/96 (45.8%) |
| fixed8k | 27/48 (56.2%) | 26/48 (54.2%) | 53/96 (55.2%) |
| 4k→8k gain | +18.8 | +18.8 | **+18.8** |
| conversions / derailments | 11 / 2 | 11 / 2 | **22 / 4** |
| sign-test p | 0.022 | 0.022 | **5.3e-4** |

The two seeds agree to one response per arm; seed variance is small. By the
frozen rule both runs pass, but they remain evidence rather than authorisation
because the gate run itself returned `inconclusive`.

## 6. Reproduction

```sh
export PYTHONPATH=week8/scaled-serving/code:week7/scaled-serving/code
python week8/scaled-serving/code/tools/analyze_slope_history.py
```

It re-pairs every fixed4k/fixed8k record by (condition, question, seed), grades
with `larb_week8.audit.grade_record(..., "normalized_safe")` and prints the
tables above. The candidate pool is built by
`code/tools/build_candidate_pool.py`.

