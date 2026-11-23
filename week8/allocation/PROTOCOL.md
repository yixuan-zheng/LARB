# Week 8 | Frozen comparison rule for question-aware allocation

This file fixes how the allocation replay is run and judged. It is committed before any replay outcome is computed. Calibration used token counts only: [run.py](run.py) loads the draws without grades for that stage. Nothing below changes after outcomes are seen.

**Question.** At the 4,096-token checkpoint, does extending by measured per-question continuation value deliver more correct-on-time answers than extending by a constant value, with arrivals, deadlines, admission and runtime held fixed?

## 1. Frozen inputs

The compare stage checks these hashes before computing anything.

| Input | SHA-256 |
|---|---|
| [draws.csv](draws.csv): 928 Experiment 2 draws | `9881c09c4cc54000c3320d0879a0d4fac9be9351f30e9aafaf92f9e795f39a02` |
| [calibration.json](calibration.json): rate, λ, value tables | `e6367abd11ae437808cf923766094e56599646f1efbf0a79d69852ceea68562f` |
| [sim.py](sim.py): the replay | `97a70f4b73071b4071ba0c922e326beda31d6f31e17acbd172adb21ac86ddb74` |
| [full-summary.json](../../week7/continuation-sampling/results/full-summary.json): value source | `47da981d4198f7273672b9590aa1dea4403ee87423f68194bc4eb39be89235c3` |
| [burst.jsonl](../../week7/scaled-serving/artifacts/traces/burst.jsonl): primary trace | `2c752e62c45d79ec35ac66c1492118d4d320fc772fd9701390378c715e63fa8b` |
| [sustained.jsonl](../../week7/scaled-serving/artifacts/traces/sustained.jsonl): context trace | `c088ae6298d9531183c23400ffe7efe557ff3b53c34f86875796c4ae1b5aed9d` |

**Value source.** Values are p8 − p4 per prefix from the published Experiment 2 summary. The prediction close-out's frozen export is expected to give one value per question. Its check is that each exported value equals the mean of that question's two prefix values. That mean includes a request's own draws, so it does not replace the other-prefix values used here. A mismatch is reported; the replay keeps the values frozen here.

## 2. Workload and rig

| Setting | Frozen value | Source |
|---|---|---|
| Trace | Burst, 1,229 arrivals rescaled to **540 requests/h** (137 min) | Fixed 8K misses 24.3% here, inside the 15–40% band. The sustained trace jumps from 1.6% at 620/h to 52.9% at 660/h, the same cliff as P1.6 |
| Requests | Every arrival is one checkpoint request. The 58 prefixes are dealt in shuffled rounds; each request gets one random short and one random long draw | `build_workload`, seed **8222** |
| Slots | 32, one FIFO queue | P1 frozen concurrency |
| Decode speed | Per-request rate by concurrency, 76.7 to 54.7 tokens/s | P1.3 sweep, `sim.RATE` |
| Deadline | 240 s from arrival | P1 fallback SLO |
| Time step | 1 s, finishes interpolated | `sim.simulate` |

## 3. Policies

All checkpoint rules use one form: extend to 8,192 if **v(q) > λ × waiting ÷ 32**, otherwise force the answer. **λ = 8.6897**, set so the constant rule extends only while nobody waits.

| Policy | Value used | Role | Extends (calibration) |
|---|---|---|---|
| **Constant** | 0.1358 for every request | Baseline | 86.2% |
| **Question-aware** | The value of the same question's *other* prefix | Tested policy | 28.4% |
| **Shuffled control** | The 58 other-prefix values dealt to prefixes at random; mean over shuffle seeds 0–19 | Isolates *which* questions are extended from *how many* | 28.6% (28.0–29.0% across the 20 shuffles) |
| Question-aware, in-sample | The prefix's own value | Ceiling only: ranked by the draws that decide its outcome | 28.4% |
| Fixed 4K, fixed 8K, arrival-only (short if 8+ wait at arrival) | — | Context, not arms | 0%, 100%, 87.3% |

## 4. Endpoints

| Endpoint | Definition |
|---|---|
| **Primary** | Paired difference in good answers (correct and on time), **question-aware − constant**, also reported as goodput per minute over the fixed 137-minute span |
| **Selection** | Question-aware − shuffled control, in good answers |
| **Fixed-budget check** | Question-aware − the better of fixed 4K and fixed 8K, in good answers, reported in the primary run and every sensitivity cell. A fixed short budget beating the adaptive rule has been the project's recurring result since Week 4 |
| Reported beside them | Correct, on time, extensions, generated tokens, median and p90 latency for every policy |
| Question-level accounting | Per question: good answers under question-aware minus constant. Count questions that gain, lose and tie; list the largest contributors |

**Uncertainty.** Resample the 29 questions with replacement, keeping both prefixes of a drawn question together. Deal the resampled prefixes into the same trace with the same workload seed, keep every value frozen, and replay. Report percentile 95% intervals.

- Primary contrast: **10,000** resamples, bootstrap seed **8226**.
- Selection contrast: **2,000** resamples, same seed.
- Each sensitivity cell: **1,000** resamples for the primary contrast.

## 5. Cost accounting

Costs use the scoring protocol's unit, the served-token equivalent: one Qwen3-4B decode token, with input tokens charged at decode cost. The value table comes from the same model, so model scale is 1.

| Cost | Definition |
|---|---|
| Serving, per policy | Generated tokens and slot-seconds (sum of finish − start) in the primary replay, total and per request |
| Building the value table | Experiment 2: 2,994,681 generated + 3,932,384 input tokens = **6,927,065** for 29 questions, **238,864 per question**; 13h 16m 20s of L40S allocation ([report](../../week7/continuation-sampling/REPORT.md)) |
| Break-even | Value-table tokens per question ÷ tokens question-aware saves per request against constant: how many requests per question must be served before the table pays for itself |

The table is charged once per question and only covers questions it has already sampled. A new question pays the full cost before its first request is served. The break-even is reported as context. It does not enter the decision rule, which judges the best case.

## 6. Sensitivity grid

Each cell changes one setting from Section 2 and is reported whatever its result.

| Cell | Change | Why |
|---|---|---|
| Rate ×0.9, ×1.1 | 486/h and 594/h | Arrival cadence |
| Speed ×0.75, ×1.25 | All decode rates | Timing model error; the Explorer and Week 6 ±25% check |
| Lag 5 s, 20 s | Decisions see the queue as it was 5 or 20 s earlier | Admission-timing error. The Week 7 replay measured phase medians of 0 to 17 s |
| Deadline 180 s | Same rate | The original P1 SLO |
| Workload seeds 8223–8227 | Five new deals of prefixes and draws | Sampling of the workload itself |

That is **11 cells**. Three extra runs are context only and not part of the sign rule:

- the sustained trace at 540/h;
- the in-sample ceiling;
- a **λ sweep**. Constant and question-aware are replayed with the anchor moved so constant extends only while fewer than 1, 2, 4 or 8 requests wait. That gives λ = 8.6897 (frozen), 2.8966, 1.2414 and 0.5793. Each anchor reports good answers, extensions and the paired difference, as point estimates. It shows whether the result depends on the one frozen λ; the verdict uses the frozen λ only.

## 7. Decision rule

| Verdict | Conditions |
|---|---|
| **Advance to a live arm** | (a) the primary 95% lower bound is above 0; (b) the primary point estimate is positive in all 11 sensitivity cells; (c) the selection point estimate is positive; (d) the fixed-budget check point estimate is ≥ 0 in the primary run; and (e) the serving go/no-go qualifies a pool and deadline |
| **Replay-only** | Primary and selection point estimates are both positive, but (a), (b), (d) or (e) fails. If (d) fails, a fixed budget does at least as well, and a live arm would need a workload where it does not |
| **Stop** | The primary point estimate is ≤ 0, or the selection point estimate is ≤ 0. In the second case the gain comes from extending less, not from knowing which questions benefit. A pressure-only rule would capture it without a value table. |

The selection test is deliberately weak: a positive point estimate, not an interval. With 29 questions, an interval above zero is unlikely even for a real effect, and requiring one would make "advance" unreachable. The report states its interval and treats a positive point with an interval spanning zero as suggestive only.

The value table is a best case. It is measured from repeated draws on the same 29 questions. A result that fails here closes the question-level allocation line; a noisier online predictor would not do better.

## 8. What does not change after outcomes

- Rate, λ, seeds, traces, deadline, policies, endpoints, grid and thresholds stay as written.
- No cell, seed or question is added or removed.
- Every request stays in the denominator, including answer caps and late answers.
- If a defect is found in the compare code after results are seen, the fix is described and both results are reported. The verdict comes from the corrected run only if the fix does not touch anything frozen above.

## Known limitations

- **One cohort, all hard.** 29 AIME 2026 questions, all already examined in Week 7. Every request is a hard one that is still reasoning at 4K; the replay has no fillers. That is the best case for allocation, because every request is a decision point. Real traffic includes requests that finish before 4K and easy ones, so a positive result here says less about a mixed serving pool.
- **The two contrasts must be read together.** At the frozen λ, constant extends 86% of checkpoints and question-aware 28%. The primary contrast therefore includes the effect of extending less, which by itself shortens queues during bursts. Only the selection contrast isolates the value of knowing which questions benefit.
- **Timing is modeled, not validated against a logged run of this workload.** No such run exists: Experiment 2 decoded one request at a time. Draw lengths are converted to time with P1 throughput. The only available check is service time with no queue (under 5 s wait) under fixed 8K. The replay gives p50 148.7 s and p90 166.0 s on the burst trace. The real rig measured 165.7 s and 183.0 s (P1.6, n = 53), on a different question pool. The replay is therefore about 10% fast, within the ±25% speed cells. Prefill is ignored. Draws are independent of the load they are replayed under.
- **Values are in-cohort.** The other-prefix value avoids grading a request on its own draws, but both prefixes share one question. This is a question-level best case, not a forecast for new questions.
