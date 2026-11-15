# 4. Dataset options for a bigger, faster study

The dataset decides whether the hypothesis is testable. This file states the requirements, records
what our own measurements say about the pools we have used, and shortlists alternatives that fit one
H100.

## 4.1 Requirements

| Requirement | Why | Rough target |
|---|---|---|
| Steep accuracy-versus-budget slope | If more thinking does not change answers, no scheduling policy can help | 8-15 points between the short and long budget |
| Mid-band accuracy | Both gains and losses must be observable; ceilings and floors both destroy signal | 35-75% at the operating budgets |
| Enough independent items | Two-to-three-point differences need hundreds of items, not dozens | 300+ items, ideally 500-1,000 |
| Cheap answers | The answer phase is currently a large share of runtime and 20-30% of outcomes are caps | Single integer, short expression, or one letter |
| Moderate trace length | Long traces mean few data points per GPU-hour and slow feedback | 1-6k thinking tokens per request |
| Acceptable contamination | AIME 2024/2025 are plausibly in pretraining data; that cannot be fixed, only recorded | Prefer recent, less-crawled, or post-cutoff material where possible |
| Grading we already trust | Changing the grader changes the meaning of "correct" | Boxed-integer plus Math-Verify, or trivial multiple choice |

## 4.2 What our own measurements say

| Pool | Measured slope | Verdict |
|---|---|---|
| AIME 2025, 30 questions x 2 seeds | 2k 30.0%, 4k 36.7%, 8k 45.0%, 16k 51.7% | Excellent slope, too few questions, expensive traces, high cap rate |
| AIME 2024, 30 questions x 2 seeds | 4k 30%, 8k 45% on a shared prefix | Same, and the only paired dataset we own |
| MATH-500, first 100 | full 95%, 2k 90%, 512 87% | Ceiling; the short budgets lose 5-8 points but the pool cannot show a scheduling benefit |
| MATH-500, 21-question slices | zero difference between 2k and unrestricted | Useless for this question; it is why several of our results are flat ties |

Two conclusions follow. AIME-shaped material is the right *kind* of data. MATH-500-shaped material is
the wrong kind, and several of our "ties" are really statements about the pool.

## 4.3 Candidate pools

Sizes are approximate and must be pinned and verified before any freeze; this table is for choosing
what to inspect, not for quoting.

| Pool | Size | Expected behaviour for a 4B model | Strengths | Risks |
|---|---|---|---|---|
| AIME 2024 + 2025 | 60 | Measured: 30-52% across the budget grid | Proven slope; integer answers; already wired up | Tiny; reused everywhere; likely contaminated |
| Older AIME years (AI-MO validation set and similar) | ~90 across 1983-2023 | Similar style, perhaps slightly easier | Triples the AIME pool in the same format | Historical AIME items are widely circulated; answer formats vary by year |
| Contemporary competition suites (HMMT, SMT, CMIMC, BRUMO via MathArena) | Roughly 30-60 per event, 150-250 combined | Similar to AIME, some easier and some harder | Recent, less contaminated, same answer style, same grader | Mixed formats; needs an answer-verification pass; per-event difficulty varies |
| Hendrycks MATH levels 4-5 | Roughly 1,000-3,000 | Likely 60-80% at generous budgets | Large; short answers; existing grader | Partly saturated; heavy overlap with the MATH-500 already used |
| Omni-MATH hard subset | 4,428 total; filter to 400-600 | Can be tuned to the 40-70% band by source and difficulty label | Large and stratified; good for controlling the accuracy band | Heterogeneous sources and formats; contamination unknown |
| GPQA (diamond subset 198) | 198 | ~30-40% for a 4B model | One-letter answers make the answer phase almost free | Guessing floor at 25%; MCQ may reward elimination rather than reasoning; small |
| GSM8K | 1,319 | ~90%+ | Cheap, short, never caps | Saturated; useful only as filler traffic |
| Synthetic or perturbed variants | Arbitrary | Controllable | Unlimited supply; can hold difficulty fixed | Construct validity; leakage; graders may not agree with the generator |

## 4.4 A practical recommendation to evaluate

- **Primary pool:** a combined AIME-family competition set - AIME 2024/2025, older AIME, and two or
  three recent MathArena events - aiming at 300-400 unique questions with integer or short answers and
  the existing Math-Verify grading. Most of it would be new to the project, which is enough to stop
  treating every result as a rerun of the same twelve questions.
- **Secondary cheap class:** MATH levels 1-2 or GSM8K, used deliberately as the *short request* traffic
  that fills the batch and creates a realistic service-time distribution. It is not the quality
  signal and should never be scored as one.
- **Optional third class:** a small multiple-choice arm (GPQA) if the answer-cap cost turns out to be
  the dominant throughput limit. It isolates that problem, at the price of a different correctness
  notion.
- **Keep a bridge.** Run one small AIME-2025 condition on the new rig so new numbers can be anchored
  to the existing results. Without a bridge, every earlier table becomes incomparable.

## 4.5 The cheap experiment that should come first

Before committing to a pool, measure its slope on the new rig. Sixty questions from each of two or
three candidate pools, three budgets (2k, 4k, 8k), one seed: about 540 responses. At a target
throughput of several hundred responses per hour that is a short run, and it answers three questions
at once: does the pool discriminate, how long are its traces, and how often does the answer cap bind.

What to record: accuracy per budget, median and p90 thinking tokens, answer-phase tokens, cap rate,
and the number of questions that change answer between adjacent budgets. A pool where fewer than 10%
of questions change answer between 4k and 8k cannot support this research.

## 4.6 Risks to state up front

- **Contamination is unfixable here.** AIME 2024/2025 are almost certainly in the model's training
  data. The plan can only record exposure and prefer newer material; it cannot claim a clean test.
- **Changing datasets breaks continuity.** Any new pool must be bridged, or six weeks of tables become
  historical curiosities.
- **Harder data is not automatically better.** AIME produces long solutions and many answer caps; a
  pool that is hard but verbose costs GPU time in the answer phase rather than the thinking phase.
- **Difficulty labels are noisy.** Stratifying by a published label is fine; filtering by observed
  accuracy is not, unless it is done on a disjoint split before the measured run.
