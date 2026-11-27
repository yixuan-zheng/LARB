# Pool decision: AIME 2025+2026

**Status:** decided and authorised before measurement. The pool then carried the
P2C/P3C/P3D serving comparisons; the original P2 sustained-rate run was stopped
by the 240 s calibration ([P2B-CALIBRATION-STOP.md](P2B-CALIBRATION-STOP.md)).
**Pre-measurement records:** `configs/pool_aime_2025_2026.json`,
`configs/qualify_aime_v1.json`. **Supporting analysis:**
[SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md).

## 1. The pool

| property | value |
|---|---|
| name | `aime-2025-2026-v1` |
| sources | AIME 2026 (30 items, `fresh`) and AIME 2025 (30 items, `exposed`), from the frozen week 7 question set |
| filters | week 7 P0 exclusion rules and self-gradable references; all 60 are integer-answer, diagram-free, non-proof and context-safe |
| selection | 12 hash-ranked items per source in the preview, the next 12 per source in the 48-item set, 6 per source held out (salt `larb-week8-aime-candidate-v1`, seed base 900000) |
| cohort | preview 24 / escalation 24 / 48 measured / 12 reserve |
| context | max prompt 767 tokens; an 8k request reserves 10,256 tokens, leaving a 1,265-token margin in the 12,288 window |
| exposure | half fresh (2026), half exposed (2025); never presented as a fresh-data claim |

No new data was fetched: the pool is a deterministic subset of the frozen week 7
questions, and `code/tools/build_candidate_pool.py` is idempotent.

## 2. Why this family, and why not the alternatives

**AIME is the only family that carries the budget slope in this rig.** Across
156 paired 4k/8k responses, AIME gains +17.2 points (18 conversions vs 3
derailments, p = 0.0015) while HMMT, CMIMC, SMT, Brumo and Omni-MATH are flat or
negative (−2.9 points over 69 pairs). The effect repeats on this pool at 48 items
on two seeds: +18.8 points each, 22 conversions vs 4 derailments over 96
responses (p = 5.3e-4). The mechanism is visible in the answers: AIME items are
still deriving when the 4k budget ends (long answer channel, 24% capped at 4k),
so more thinking converts; Omni-MATH items conclude early and re-derive the same
wrong answer.

**Why not AIME 2023.** It is the cleanest witness of the slope (6/24 → 13/24),
but 25 items at 4 seeds give a 16–21-point MDE: it can show that the effect
exists, not compare arms. It stays evidence, not the cohort.

**Why Omni-MATH was dropped.** The 24-item preview showed no slope (−4.2 points,
8k accuracy 29.2%, 4.2% answer caps); the verdict was robust to the grader
(safe 8/7/7, loose 8/8/8, exact 8/7/7). The family analysis shows this is a pool
property — answer churn without conversion — not bad luck. The raw stop record
is `results/p2a/` (`STOP.md`, `decision.json`, preview records).

**Why not a larger pool now.** 400–600 AIME-style items do not exist in the
frozen source. 60 items at 4 seeds still resolve a 10–13-point difference, which
is the scale of the effects these serving comparisons are about. Expanding the
pool is a later resolution extension, not a silent change to this one.

## 3. Power and limits (declared before P2)

- **MDE.** 60 questions × 4 seeds: 80% power against roughly 10–13 points at ICC
  0.2–0.6 and 20% discordance. A 5-point claim is not supported. The smaller
  screening runs (P2C 240/arm, P3C/P3D 180/arm) have MDEs of roughly 10–16
  points.
- **Answer space.** Held constant at the legacy 2,048-token allowance so arm
  differences stay comparable with P1 and P2A. At trace scale expect 6–8% of 8k
  answers and 17–25% of 4k answers to hit the allowance; they stay in the
  denominator and are graded wrong.
- **Exposure.** Half the pool is `fresh` (AIME 2026), half `exposed` (AIME 2025).
  Report the halves separately.
- **Unseen subset.** 12 items never entered the preview; report them as a
  separate descriptive check.
- **One block.** Qwen3-4B, one H100, one block; the result is a serving-policy
  result on a public benchmark.

## 4. Open options

- **Pool filtering** on derivation length is not applied: it would cut the pool
  below 60 items and reduce representativeness. Trigger to reconsider: an 8k arm
  showing more than 20% answer caps on the frozen traces.
- **Answer space** stays at 2,048 tokens. The 12,288 window cannot reserve a
  larger allowance at 8k thinking, and changing it would break comparability
  with P1/P2A.
