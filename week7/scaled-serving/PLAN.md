# Week 7 scaled serving: execution plan

**Status:** draft for sign-off. This document authorises no GPU job.
**Basis:** the binder in `binder/01-current-rig.md` ... `binder/06-engineering-gaps.md`, plus the CPU-only
feasibility checks in [plan/12-feasibility-notes.md](plan/12-feasibility-notes.md).
**Chosen strategy:** *realism-first* (user decision, 2026-11-13). The main path prioritises a
32-way-concurrent, mixed-traffic, exogenous-deadline serving rig over resolving a 3-point effect.
The plan is still built so that a clean 5-6 point result is possible, and so that a 3-point claim
can be earned later by extension rather than asserted from an underpowered sample.

**Reading order:** this file -> [plan/09-main-path.md](plan/09-main-path.md) -> [plan/07-rig-design.md](plan/07-rig-design.md)
-> [plan/08-experiment-design.md](plan/08-experiment-design.md) -> [plan/12-feasibility-notes.md](plan/12-feasibility-notes.md)
-> [plan/10-risk-register.md](plan/10-risk-register.md) -> [plan/11-open-questions.md](plan/11-open-questions.md)
-> [plan/13-artifact-and-reproduction.md](plan/13-artifact-and-reproduction.md).

## 1. What is being tested

The working hypothesis is unchanged:

> Under bursty or sustained load, shortening the thinking budget of requests already running when
> the queue builds delivers more correct-by-deadline answers than (a) choosing the budget once at
> admission or (b) a fixed short budget, while keeping eventual accuracy within about 3 percentage
> points of full thinking.

Operational claims, in the order the main path tests them:

| ID | Claim | Main comparison | Role |
|---|---|---|---|
| **H1** | Pressure cuts raise correct-on-time goodput over a fixed short budget | `live` vs `fixed4k`, pooled over sustained and burst/recovery; condition-specific results secondary | Primary |
| **H2** | The in-flight cut adds value beyond choosing a short budget at admission | `live` vs `arrival`, burst/recovery primary; sustained descriptive | Primary |
| **H3** | The accuracy cost of `live` is bounded relative to full thinking | `live` vs `fixed8k`, eventual accuracy | Secondary, non-inferiority |
| **H4** | `live` spends less work or latency than full thinking at comparable goodput | `live` vs `fixed8k`, tokens/latency/throughput | Secondary |

Relation to the closest work: the binder's audit (binder/03-related-work.md) found that most published
serving results are simulations, and that none puts a tuned global token cap beside an adaptive
reasoning policy. This plan executes the real engine, scores answers, and treats `fixed4k`/`fixed8k`
as first-class competitors. That is the gap it is designed to fill, not a claim of novelty over any
specific paper.

Definitions used everywhere:

- **Correct on time:** correct final answer, normal completion, received by the client before the
  request's declared deadline. Caps, errors, missing outputs and late answers stay in the
  denominator and count as failures.
- **Pressure conditions:** the frozen `sustained` and `burst` traces. `low` is a no-queue control
  and is never pooled with them.
- **`live`:** uses the same queue-aware admission rule as `arrival` (8,192 when the same-phase
  waiting count is below threshold, 4,096 when at or above it), plus one irreversible in-flight cut
  toward 4,096 per pressure step on an eligible running request; new admissions after pressure
  clears may still receive 8,192, and a cut request never recovers.
- **Full thinking:** 8,192 tokens in the serving rig. This is the largest budget that fits 32
  concurrent requests in the 80 GB KV budget (see plan/12-feasibility-notes.md, section 3). A 16,384
  bridge is a separate, lower-concurrency check, not the main reference.

## 2. What "realistic" means here

The main path commits to the following, all fixed before measurement:

| Dimension | Main-path choice | Why |
|---|---|---|
| Concurrency | `max_num_seqs = 32`; gate also measures 16 and 24 | Makes the queue a queue rather than a binary artefact. KV fits at the chosen 8k budget. |
| Traffic | 70% scored signal requests + 30% unscored short filler | Produces a service-time distribution and keeps the batch full; filler is never scored. |
| Arrivals | Frozen trace: Poisson sustained load, plus burst/recovery; seeded and replayed identically across arms | Real queueing statistics and repeatable comparisons. |
| Deadlines | Declared 180 s service-level objective for all requests, measured from client arrival; load is tuned to put the reference arm's signal requests at 15-40% misses | The metric has room to move and is exogenous to any arm's own latency. |
| Engine | Real vLLM 0.11.2, Qwen3-4B BF16, continuous batching | Keeps the object of study real; no simulator. |
| Execution | CUDA graphs enabled only after an exact-cue equivalence gate; eager fallback | Recovers throughput without silently changing the experiment. |
| Answer phase | Legacy 2,048-token contract by default; a short forced-boxed contract may replace it only after a bridge gate | The answer phase is currently 20-30% caps and a large share of service time. |
| Telemetry | Per-request timestamps, queue snapshots, KV occupancy, preemptions, GPU utilisation | The binder's missing instrumentation is now part of the measurement. |
| Cohort | 200-246 signal questions from 2025-2026 competition pools, 4 seeds; 6 only as an extension if throughput is exceptional | Realism-first; enough for a 5-6 point result, not a 3-point one. |
| Arms | `fixed4k`, `fixed8k`, `arrival`, `live` | The two real competitors plus the mechanism. `fixed6k` is a calibration/extension arm. |
| Replication | One 16 h main job; a second block or a larger cohort is a gated extension | Fits the 16 h `ice-gpu` limit and the calendar. |

What deliberately stays as it was: the model and revision, the vLLM/torch/transformers pins, the
grading stack, the pairing of questions and seeds across arms, the rule that failures stay in the
denominator, and the separation of frozen measurement code from analysis code.

## 3. Resolution: what the main path can and cannot show

The planning numbers, derived in [plan/12-feasibility-notes.md](plan/12-feasibility-notes.md):

- 215 signal questions x 4 seeds = 860 signal responses per arm per condition. With 30% filler and
  four arms, the main run is about 10,520 requests. The arm-average output length is about 6k
  tokens: `fixed4k` is about 4.1k, `fixed8k` about 8.1k, and `arrival`/`live` sit between them.
  At 1,000 tokens/s aggregate that is about 17.5 h and does not fit; at 1,500 it is about 11.7 h;
  at 2,000 it is about 8.8 h. Gate C therefore chooses 4 seeds only above about 1,500 tokens/s and
  drops to 3 or 2 seeds below that. The low-load control is a short addition.
- The 12-question AIME slice in week 6 has a question-level intraclass correlation of roughly
  0.6-0.8: most questions are always right or always wrong. That slice is an extreme, deliberately
  selected set. The planning assumption for a broad 200-250-question pool is ICC 0.2-0.4; the
  reported result will include the realised ICC.
- At 880 responses per arm, 220 questions x 4 seeds, ICC 0.2-0.4 gives about 400-550 effective
  paired question units. With 15-20% discordance, the 80%-power minimum detectable effect is about
  **5.3-6.3 percentage points**, not 3. If the realised ICC is 0.6, the MDE is about 7 points.
- Therefore the main path is powered for a **5-6 point** effect, at the edge for 5. If Gate C
  reduces the run to 3 seeds, the MDE rises to roughly 6-7 points; the report uses the realised N.
  The 3-point clause is **not** resolvable at this cohort size. The report will give the confidence
  interval and say what it excludes; a 2-3 point observed difference will not be called a tie or a
  win. Resolution-first (500-800 questions, or a second block) is a gated extension, not a silent
  promise.

## 4. Main path at a glance

| Phase | What it does | GPU cost | Exit gate |
|---|---|---:|---|
| **P0** | Freeze protocol, acquire and QC datasets, build the trace, port the controller, write CPU tests, run the synthetic rehearsal | 0 | Protocol and dataset manifest hashed; all CPU tests pass |
| **P1** | One GPU gate job: rig bridge, 32-row mechanics, graph equivalence, concurrency/throughput sweep, answer-contract bridge, slope screen, load/deadline calibration | 6-8 h | Every gate in plan/09-main-path.md passes |
| **P2** | Main run: four arms x two pressure conditions + low-load control, on the frozen trace | 10-16 h | Coverage and manipulation checks pass |
| **P3** | Grading, paired analysis, report, reproduction package | 0 | Primary CI and decision recorded |
| **P4** | Conditional extension: second block, larger cohort, `fixed6k`, policy variants, 8B bridge | 16 h+ | Only if P3 says the question is still open |

The main path is **P0-P3**. P4 is authorised only by a specific P3 outcome (section 5).

## 5. Decision rules

| Outcome | Interpretation | Action |
|---|---|---|
| `live - fixed4k` CI lower bound > 0 and point estimate >= 5 points in the pressure conditions | H1 supported at the planned resolution | Proceed to H2/H3/H4 reporting; prepare a replication extension |
| `live <= fixed4k` in both pressure conditions | H1 is false as written | Stop the serving branch; report the fixed-budget result and pivot to a different lever or model |
| `live` beats `fixed4k` but the `live - fixed8k` accuracy gap is > 5 points | The mechanism buys goodput by spending too much accuracy | Do not make a serving claim; revise the cut rule (later, smaller, selective) and re-test in a new experiment |
| Difference is 2-5 points with a CI spanning 0 | Underpowered, not a tie | Extend to 500-800 questions or a second block; do not change the policy |
| `fixed6k` (if run) matches `live` on goodput and accuracy | The simpler static budget wins | Report the static-budget result; retire the adaptive claim unless it has another advantage |
| Graph gate changes cue positions or token-level outputs | Graphs are a different experiment | Keep eager for the main run, or report graph and eager as separate experiments |
| Throughput at 32 slots is < 1,500 output tokens/s | The full 4-seed N does not fit 16 h | 3 seeds at 1,200-1,500; 2 seeds at 1,000-1,200; split the run below 1,000. Do not claim a throughput result from an overloaded run |
| Slope screen shows < 8 points between 4k and 8k, or < 10% question-level answer changes | The pool cannot carry the hypothesis | Change pool (Omni-MATH hard subset or a different event family) before measuring |
| Reference-arm miss rate is outside 15-40% after load tuning | The deadline/metric is saturated or decorative | Adjust arrival rate, not the deadline; if no rate works, revise the declared SLO before the main run |
| A phase fails coverage or injection validity | Not a policy result | Preserve the record, rerun only the missing phase from the frozen trace; never discard the arm |

No threshold, dataset, deadline or arm may be changed after the main-run scores are seen. A tie is
a result, and a `fixed4k` win is a result. The experiment's job is to measure the hypothesis, not
to defend it.


## 6. Out of scope for the main path

- Models larger than Qwen3-4B (an 8B bridge is an extension).
- Multi-node or tensor-parallel serving.
- Learned predictors, confidence probes or trajectory readers. Week 6 stopped that branch; the main
  path does not reopen it.
- Speculative decoding, multi-LoRA, priority tenants, real production trace replay.
- Online adaptation of the pressure threshold or the cut target.
- Claims about training-data contamination beyond the recorded exposure tags.

## 7. Deliverables

1. `PROTOCOL.md`: the frozen hypothesis, arms, conditions, deadlines, pressure rule, endpoints and
   stopping rules.
2. `DATASETS.md` and a manifest with source, revision, license, hashes and exposure tags.
3. `TRACE.jsonl` plus its SHA-256, one trace per condition, shared by all arms.
4. `source-lock.json`: executed code hashes, model revision, engine and library versions, GPU
   metadata.
5. Raw per-request records, token IDs for scored requests, sampled scheduler snapshots, cut events,
   GPU/KV/preemption telemetry.
6. `analysis.json`, `REPORT.md`, and a CPU reproduction script that regenerates every headline
   number from the stored records.
7. A decision memo that states whether H1/H2/H3/H4 were supported, refuted or left unresolved.

## 8. Sign-off

The defaults above are recommendations, not facts. The decisions that need an explicit owner are
listed in [plan/11-open-questions.md](plan/11-open-questions.md), each with a recommended default. The two
that most change the plan are the declared SLO (180 s vs 240 s) and whether the short-answer
contract may replace the legacy contract in the main run.

