# Pool decision: 2023 AIME witness and the Omni-MATH fallback

**Status:** pre-measurement decision record, now resolved by the GPU preview.
The Omni-MATH fallback **failed** the preview gate on 2026-11-16 (see
§5); the reasoning below is the pre-declared basis and is unchanged by the
outcome.
**Basis:** `week7/scaled-serving/reports/P1-REPORT.md`, `plan/09-main-path.md` P1.5,
`plan/11-open-questions.md`, `week8/PLAN.md`, and the records audit in
[P1-SCREEN-AUDIT.md](P1-SCREEN-AUDIT.md).

## 1. The candidate 2023 AIME intersection

The P1 slope screen contains 24 of the 25 eligible AIME 2023 items (all but
`aime2023-I-009`), with the exact processed prompts and the frozen grading
contract. The audit checked all 216 slope records: **0 prompt issues** (the
question text is verbatim, the reference matches, the chat-template prefix and
suffix are present, and the token-count proxy agrees within 40 tokens).

Using the safe normalised grader (exact match, then Math-Verify only when the
parse is not lossy):

| Subset | n | 4k accuracy | 6k accuracy | 8k accuracy | 4k→8k gain | answer change | 8k cap | passes the pre-registered AND rule |
|---|---:|---:|---:|---:|---:|---:|---:|---|
| AIME 2023 | 24 | 25.0% (6) | 37.5% (9) | **54.2% (13)** | **+29.2 pts** | **70.8%** | 8.3% | **yes** |
| HMMT Feb 2024 | 24 | 29.2% (7) | 25.0% (6) | 33.3% (8) | +4.2 pts | 66.7% | 12.5% | no |
| Screen all | 48 | 27.1% (13) | 31.2% (15) | 43.8% (21) | +16.7 pts | 68.8% | 10.4% | yes |
| Main-cohort preview | 24 | 25.0% (6) | 29.2% (7) | 16.7% (4) | -8.3 pts | 50.0% | 20.8% | no |

The screen's aggregate pass is carried by the AIME 2023 half. The HMMT 2024
half does not carry the same slope, and five of its responses were false
negatives caused by `\dfrac` references that the installed Math-Verify build
cannot parse. Loose Math-Verify also produced one false positive on
`cmimc2025-036`: it parsed `3 - 2\sqrt{2}` and
`3 + \sqrt{2} + \sqrt{3} + \sqrt{6}` both as `3`. The Week 8 preview therefore
uses the safe rule, not the loose P1 grader.

**Verdict:** the 2023 AIME intersection is a valid *slope witness*. It is not a
suitable *main pool*: 25 independent questions at 4 seeds give an 80%-power
MDE of about 15.8-21.0 points at ICC 0.2-0.6 and 20% discordance. That cannot
resolve the project's 5-6 point question, let alone 3 points. It is retained
as a witness and as the cleanest available check that the engine and grader
can show a 4k→8k slope.

## 2. Pre-declared fallback pool: Omni-MATH hard subset

The P1 report names the Omni-MATH hard subset as the fallback. It is
pre-declared here, before any preview measurement, as `omni-math-hard-v1`.

**Source:** `KbsdJames/Omni-MATH`, revision
`40ba231d8f16e29ecd40e6407e2c8640145a8f62`, Apache-2.0, `test.jsonl`,
SHA-256 `7c87be8e...ef168`, 4,428 rows.

**Filters, all applied before any model outcome is seen:**

1. Published difficulty in `[5.0, 8.0]`.
2. Non-empty problem and answer; answer at most 160 characters; prompt at most
   1,850 local tokens (the exact chat-template maximum is 324 tokens, leaving a
   1,708-token margin under the 12,288-token model window).
3. The frozen week 7 exclusion rules: no proof-like, diagram-dependent,
   multiple-choice, missing-answer or oversized-answer items.
4. The reference must be self-gradable by the frozen boxed extractor + exact
   matcher (wrapping the reference in `\boxed{...}` and grading it against
   itself). This rejected 33 items at the 5-8 band.
5. Natural-language `\text{...}` answers are excluded.

**Selection:** three published-difficulty strata, 80 items each:

| Stratum | Selected | Sources | Source cap |
|---|---:|---:|---:|
| 5.0-6.0 | 80 | 40 | 20 per source |
| 6.0-7.0 | 80 | 45 | 20 per source |
| 7.0-8.0 | 80 | 39 | 20 per source |
| **Total** | **240** | **59** | |

Round-robin across sources with a 20-per-source cap prevents one event family
from dominating; the cap was not relaxed. The selected pool has 74 integer and
166 expression answers, mean difficulty 6.25.

**Cohort split, frozen by hash rank:**

| Set | n | Role |
|---|---:|---|
| Main | 216 | Four-arm main run if the 24-item preview passes |
| Preview | 24 | 8 per stratum; excluded from main |
| Preview escalation | 24 | 8 per stratum; used only if the 24-item preview is a near-miss |
| Main after escalation | 192 | Main cohort if the 48-item preview is used |
| Calibration | 48 | 16 per stratum from the main-after-escalation cohort |
| Filler | 92 | Reused from the frozen week 7 MATH-500 filler pool |

**Why Omni-MATH rather than an AIME-family pool.** An AIME 2023+2024+2025+2026
pool would be easier to grade but would reuse the project's most-used AIME
questions, include the AIME 2025 bridge in the main comparison, and contain
only about 114 items. Omni-MATH supplies 240 items from 59 sources with a
published difficulty spread, and the preview is the explicit gate. The
AIME-family pool remains a reserve if the Omni-MATH preview fails on grading
or on the accuracy band; it is not an alternative arm in this week's run.

**Why not a larger cohort now.** 240 selected items produce 216 main questions.
At 4 seeds the 80%-power MDE is about 5.4-7.1 points at ICC 0.2-0.6 and 20%
discordance. A pre-declared wall-time rule may reduce the pressure-condition
seed count to 3 (at roughly 750-950/h) or 2 (below roughly 750/h) so the run
fits the 15 h inner allocation; at 3 seeds the MDE rises to about 5.8-7.3
points, and at 2 seeds to about 6.6-8.9 points. The realised seed count and
MDE must be reported. This is the same 5-6 point resolution the week 7 plan
already accepted, not a 3-point design. Expanding to 400-600 questions is a
later resolution extension, not a silent change to this one.

## 3. Limitations recorded before measurement

- **Exposure.** Every Omni-MATH item is tagged `exposed`. This is a serving
  policy test on a public benchmark, not a fresh-data claim. The result must
  be reported with that limitation.
- **Heterogeneous formats.** 166 of 240 answers are expressions. The safe
  grading rule is stricter than the P1 loose Math-Verify rule; equivalent
  forms that do not normalise to the reference count as wrong. The preview
  reports the missing-box and mismatch rates, and a grader failure is a
  documented stop, not a pool failure.
- **Preview power.** The 24-item preview can only detect a large slope. A
  one-answer to sub-8-point gain (the pre-declared near-miss band, 4.0-8.0
  points) triggers the 48-item escalation; a smaller gain stops the line.
- **One block, one model, one GPU.** The final result remains a Qwen3-4B,
  one-H100, one-block result.

## 4. What must be true before P2

P2 is authorised only if all three hold:

1. The 24-item preview (or the 48-item escalation after a near-miss) passes
   the pre-registered AND rule: ≥8 point 4k→8k gain, ≥10% answer change, 8k
   accuracy in `[0.35, 0.75]`, 8k cap rate ≤20%, 8k thinking median ≤8192,
   full coverage and a gradable response rate.
2. The 240 s calibration finds a rate in the 15-40% reference miss band,
   with the pre-declared grid and at most one refinement round.
3. The live manipulation check fires at least one in-flight cut, has positive
   pressure at waiting ≥8, never cuts after the close token, and produces both
   4096 and 8192 admissions.

If any condition fails, the correct outcome is a documented stop with the
artifact and the reason. The stop is a result.

## 5. Measured outcome (2026-11-16)

The 24-item preview returned **stop**: 8/24 at 4k, 7/24 at 6k, 7/24 at 8k
(gain -4.2 points), 8k accuracy 29.2%, cap rate 4.2%, answer change 62.5%,
coverage and grader valid. The verdict is grader-robust (safe 8/7/7, loose
8/8/8, exact 8/7/7, raw 10/8/9). Condition 1 of §4 therefore fails, and
conditions 2-3 were not attempted. The AIME-family reserve pool named in §2 is
the next candidate; it needs its own pre-declaration and preview. Records:
`results/p2a/PREVIEW-24.md`, `results/p2a/STOP.md`,
[P2A-STATUS.md](P2A-STATUS.md).
