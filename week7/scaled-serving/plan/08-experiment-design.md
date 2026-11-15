# 8. Experiment design

This file turns the hypothesis into a pre-registerable experiment. It is written for the
realism-first main path: 32-way concurrency, mixed signal/filler traffic, a declared 180 s SLO, and
200-246 signal questions. The main path is powered for a 5-6 point effect, not 3; the resolution
extension is specified separately.

## 8.1 Estimands

For arm `a` in condition `c`, let `Y_i(a,c)` be the primary outcome for signal question `i`,
averaged over its seeds:

```
Y_i(a,c) = (1 / planned_seeds) * sum over planned seeds of
           1[correct, normal completion, client receipt <= deadline]
```

A missing, errored, capped or late response contributes 0; the planned denominator does not shrink
because a request failed.

The estimand is the paired difference:

```
Delta(a,b | c) = mean_i [ Y_i(a,c) - Y_i(b,c) ]
```

with questions as the independent unit and seeds as repeated measurements. The same `(question,
seed)` pairs appear in both arms. Secondary estimands are eventual accuracy (correct regardless of
timeliness), deadline attainment, cap rate, latency, tokens and throughput.

The operational claims are H1-H4 in [PLAN.md](../PLAN.md), section 1. The primary comparison is
`live` vs `fixed4k`, pooled over the two pressure conditions with condition as a fixed block;
condition-specific estimates are secondary. `live` vs `arrival` tests whether in-flight
intervention adds anything beyond an admission decision, and is read primarily from `burst/recovery`
because the shared admission rule leaves `live` few in-flight cuts in sustained overload. `live` vs
`fixed8k` tests the accuracy cost and the efficiency benefit. No other comparison is primary.

H3's reference is `fixed8k`, the largest budget that fits 32-way concurrency. The original 3-point
clause was written against 16k full thinking. Unless a 16k bridge is run at lower concurrency, the
report can claim only a bound relative to 8k, not the original full-thinking claim. The bridge is a
gated extension, and the wording of the conclusion must reflect which reference was actually run.

## 8.2 Dataset plan

### 8.2.1 Candidate pools

Sizes were checked against the MathArena dataset server in November 2026. The final manifest must
pin the revision, file hash and license before any run.

| Pool | Items | Role | Answer format | Exposure tag |
|---|---:|---|---|---|
| AIME 2025 (`MathArena/aime_2025`) | 30 | Rig bridge only; not in the main cohort | integer | exposed |
| AIME 2026 (`MathArena/aime_2026`) | 30 | Main, fresh | integer | fresh |
| HMMT Feb 2025 (`MathArena/hmmt_feb_2025`) | 30 | Main, recent | short expression | recent |
| HMMT Nov 2025 (`MathArena/hmmt_nov_2025`) | 30 | Main, fresh | short expression | fresh |
| HMMT Feb 2026 (`MathArena/hmmt_feb_2026`) | 33 | Main, fresh | short expression | fresh |
| SMT 2025 (`MathArena/smt_2025`) | 53 | Main, recent | expression | recent |
| BRUMO 2025 (`MathArena/brumo_2025`) | 30 | Main, recent | expression | recent |
| CMIMC 2025 (`MathArena/cmimc_2025`) | 40 | Main, recent | expression | recent |

Raw total: 276. After excluding non-gradable, diagram-dependent, duplicate or out-of-scope items,
the planning cohort is **200-246 signal questions**. The main path uses all remaining items in the
selected pools; there is no item-level filtering on observed accuracy.

The fresh subset is AIME 2026 + HMMT Nov 2025 + HMMT Feb 2026 = 93 items (about 80 after QC). It is
analysed separately, not pooled silently with the exposed subset. A result that appears only in the
fresh subset is interesting but underpowered; a result that appears only in the exposed subset is
weaker evidence because of contamination.

### 8.2.2 Filler pool

MATH-500 levels 1-2 or GSM8K, disjoint from the 124 MATH indices already consumed by the project.
Filler requests use a fixed 1,024-token thinking budget, are never scored, and exist to create a
service-time distribution. They are assigned the same 180 s deadline and counted in system metrics,
not in accuracy.

### 8.2.3 Exclusion rules

Exclude an item if any of the following is true:

- The answer is a proof, a construction, or a free-form response that Math-Verify cannot compare.
- The item depends on a diagram or image that is not rendered in the text.
- The item is duplicated (same problem text) within or across pools.
- The item has no verifiable reference answer.
- The item's prompt exceeds the context budget after tokenisation.

Record every exclusion with its reason and hash. No exclusion may be made after seeing a model
output.

### 8.2.4 Bridge

A 30-question AIME 2025 bridge is run on the new rig with `fixed4k` and `fixed8k`, two seeds, and
the legacy cue/answer contract. It is compared with the saved week 5 result (4k 36.7%, 8k 45.0% on
60 responses per budget). The bridge is a rig-validity check, not evidence for H1. If the new rig's
accuracy differs by more than about 10 points at either budget, stop and debug before the main run.
The bridge questions are not in the main cohort, so this is not a reuse of the main data.

### 8.2.5 Grading

Use the existing boxed-answer extraction plus Math-Verify 0.9.0. A capped output is wrong. A
missing or unparsable output is wrong. A wrong answer with a confident format is wrong. Keep a
manual review queue for every wrong, ambiguous or capped answer; raw text is retained. Manual
corrections are allowed only under the week 3 hash-and-reason protocol and are reported separately
from the uncorrected score. The main analysis does not change the grader after seeing outcomes.

## 8.3 Slope screen

The screen is a go/no-go on the pool, not a miniature hypothesis test.

- **Items:** 48 questions drawn from disjoint 2023-2024 events (AIME 2023 I/II and HMMT Feb 2024,
  24 each). They are not in the main cohort. In addition, 24 questions are sampled from the main
  cohort as a preview; they are excluded from the main analysis, so the main cohort shrinks by 24
  (the 200-246 planning range already allows for this).
- **Budgets:** 4,096, 6,096, 8,192; one seed; legacy answer contract.
- **Responses:** 48 x 3 = 144 disjoint + 24 x 3 = 72 main-cohort preview = 216. At the gate
  throughput this is a short run.
- **Decision:** the disjoint screen validates the method and the pool family; the main-cohort
  preview is the one that decides whether the main run proceeds. A method that passes on 2023-2024
  but fails on the 2025-2026 preview is a pool problem, not a green light.
- **Record:** accuracy per budget, median and p90 thinking tokens, answer tokens, cap rate, and the
  fraction of questions whose answer changes between 4k and 8k.
- **Pass:** at least an 8-point accuracy gain from 4k to 8k, or at least 10% of questions changing
  answer between those budgets; 8k accuracy in the 35-75% band; cap rate at most 20% under the
  chosen answer contract; median thinking tokens at most 8k.
- **Fail:** change pool before the main run. The fallback is an Omni-MATH hard subset filtered by
  source and published difficulty, never by observed accuracy on the main cohort.

The screen also reports whether a fixed 6,096 budget sits close to 8,192. If it does, the default is
a separate short block (the main cohort x 2 seeds, `fixed6k` vs `fixed8k`, about 440 responses per
arm) rather than a fifth arm in the 16 h main job. A fifth arm is added to the main run only if Gate
C measures enough throughput (roughly 2,000 output tokens/s) to keep the job inside 16 h. The main
path never assumes the extra arm.

## 8.4 Answer-contract bridge

The legacy contract spends a median of 1,371 answer tokens and caps 22-33% of measured responses
on the AIME work. A short answer contract could recover a large fraction of throughput, but it
changes what "correct" means. It is therefore a gated rig change, not an assumed improvement.

- **Items:** 48 questions from the screening pools, disjoint from the main cohort.
- **Budgets:** 4,096 and 8,192.
- **Seeds:** 2 per question per contract.
- **Contracts:** legacy 14-token cue + 2,048-token answer allowance; `short_boxed` cue +
  128-token answer allowance.
- **Responses:** 48 x 2 x 2 x 2 = 384.
- **Pass:** the paired accuracy difference between contracts is within 2 points (with a CI that
  does not suggest a large loss), the cap rate is lower, and the median answer phase is below 256
  tokens.
- **Fallback:** use the legacy contract for the main run and accept the throughput cost. Do not
  mix contracts across arms.
- **If the short contract passes:** it is used for every arm in the main run. The bridge result is
  reported as a rig-validity check, not as a hypothesis result.

The short contract is not allowed to change the thinking budget or the cue's position in the
trajectory. It changes only what happens after the thinking phase ends.

## 8.5 Conditions, arms and traces

### 8.5.1 Conditions

| Condition | Arrival process | Purpose | Pressure expected |
|---|---|---|---|
| `low` | Low Poisson rate; no queue | No-queue control; proves the controller does nothing when it should | None |
| `sustained` | Poisson at calibrated capacity-relative rate | Constant pressure; the fixed-short competitor's best case | Frequent |
| `burst` | Low baseline, scripted burst, recovery | Intermittent pressure; hold/cut/restore in one run | Intermittent |

The main path runs all three. `low` is short (60 signal questions x 2 seeds per arm in the P0
schedule; 100 is the planning ceiling if throughput allows). `sustained` and `burst` use the full
cohort (200-246 questions x 4 seeds per arm). If the GPU budget is tight, the first thing to shrink
is the low-load control, not the pressure conditions.

One expectation must be stated before the run: in `sustained` overload, the queue-aware admission
rule may already choose 4,096 for most arrivals, so `live` may have few requests admitted at 8,192
and few in-flight cuts. H2 (`live` vs `arrival`) is therefore read primarily from `burst/recovery`,
where requests admitted during slack are later exposed to a queue. A tie in `sustained` is an
expected consequence of the shared admission rule, not evidence against the mechanism. This is why
both conditions are run and reported separately.

### 8.5.2 Arms

| Arm | Role | Main path? |
|---|---|---|
| `fixed4k` | Fixed short competitor | Yes |
| `fixed8k` | Full-thinking accuracy reference | Yes |
| `arrival` | Admission-only control | Yes |
| `live` | Pressure-triggered in-flight cut | Yes |
| `fixed6k` | Middle-of-grid static competitor | Calibration; promoted only if the slope screen says it is competitive |
| `live_all`, `live_late`, `live_deadline` | Policy variants | Extension only |

### 8.5.3 Trace construction

1. Generate the question/seed assignment from the frozen cohort and seed bases.
2. Generate the arrival offsets from the seeded process for the condition.
3. Interleave filler requests at 30% of arrivals, with their own seeds and a fixed 1,024 budget.
4. Assign the declared 180 s deadline to every request.
5. Validate: unique request ids; identical question/seed/offset/deadline sets across arms; all
   prompt hashes present; no missing reference; total arrivals match the planned N.
6. Hash the trace bytes and freeze it before the first measured phase.
7. Replay the same trace for each arm. The only difference is the arm label and the policy.

### 8.5.4 Order and blocking

The main run is one block of phases:

- `low`: fixed4k, fixed8k, arrival, live.
- `sustained`: fixed4k, fixed8k, arrival, live.
- `burst`: live, arrival, fixed8k, fixed4k (reverse order).

A second block, if run, reverses the sustained and burst orders and uses a different seed base. Two
blocks do not fully counterbalance four arms; they let the report separate a stable effect from a
run-order accident. One block is the main path; two blocks are an extension.

### 8.5.5 Warm-up and phase boundaries

Each phase: 20-30 unscored filler warm-up requests, drain, then the measured trace. Between phases:
drain, record drain time, keep the engine process alive. If the engine crashes, restart and replay
the phase from the frozen trace; record the restart. A phase with injection lag above 1 s is
invalid and is repeated, not analysed as a policy result.

The phase horizon is `last_scheduled_arrival + deadline + drain_allowance` (the drain allowance is a
fixed config value, e.g. 300 s). A request that finishes after its deadline is recorded late, not
killed. A phase is never terminated early to make a policy look better; the runner waits for the
horizon or a crash.

### 8.5.6 Expected response counts

| Block | Signal per arm/condition | Seeds | Signal responses per arm/condition | Filler (30%) | Total per arm/condition |
|---|---:|---:|---:|---:|---:|
| `sustained` | 220 | 4 | 880 | 377 | 1,257 |
| `burst` | 220 | 4 | 880 | 377 | 1,257 |
| `low` | 60 | 2 | 120 | 52 | 172 |

Four arms x (1,229 + 1,229 + 172) = 10,520 requests. The arm-average output length is about 6k
tokens (`fixed4k` about 4.1k, `fixed8k` about 8.1k, the adaptive arms between), so the run is about
63M output tokens. At 1,000 output tokens/s aggregate this is about 17.5 h and does not fit; at
1,500 it is about 11.7 h; at 2,000 it is about 8.8 h. The throughput gate therefore chooses 4 seeds
only above about 1,500 tokens/s, 3 seeds at 1,200-1,500, and 2 seeds or a split run below 1,200.
`experiment-matrix.csv` shows the full 4-seed design; the realised seed count is recorded in each
phase's `phase.json` and used in the analysis.


## 8.6 Sample size and power

The planning table, with the algebra in [12-feasibility-notes.md](12-feasibility-notes.md):

| Signal questions | Seeds | Responses/arm/condition | n_eff at ICC 0.2 | n_eff at ICC 0.4 | n_eff at ICC 0.6 | MDE at disc 0.20, ICC 0.2-0.4 |
|---:|---:|---:|---:|---:|---:|---:|
| 200 | 4 | 800 | 500 | 364 | 286 | 5.6-6.6 pts |
| 220 | 4 | 880 | 550 | 400 | 314 | 5.3-6.3 pts |
| 246 | 4 | 984 | 615 | 447 | 351 | 5.1-5.9 pts |
| 220 | 6 | 1,320 | 660 | 440 | 330 | 4.9-6.0 pts |
| 500 | 4 | 2,000 | 1,250 | 909 | 714 | 3.5-4.2 pts |
| 800 | 4 | 3,200 | 2,000 | 1,455 | 1,143 | 2.8-3.3 pts |

The main path uses 220-246 questions x 4 seeds as the planning point. At ICC 0.2-0.4 it is powered
for a **5-6 point** effect; a 5-point effect is at the edge, and the realised ICC decides. If Gate C
reduces the run to 3 seeds, the effective pairs fall by about 25% and the MDE rises to roughly 6-7
points; the report uses the realised N and reports the weaker resolution rather than the planned
one. The 3-point clause requires roughly 500-800 questions at this ICC, or a second block that
increases the independent-question count. The report must state the realised ICC and the realised
MDE, not just the planned one.

The primary analysis uses a cluster bootstrap by question. If the observed effect is 2-5 points
with a CI spanning zero, the result is "unresolved at this sample size," not "no effect." If the
observed effect is >=5 points and the CI excludes zero, the result is a clean main-path finding.

## 8.7 Analysis plan

### 8.7.1 Primary

For H1, pool the two pressure conditions with condition as a fixed block; report the
condition-specific estimates as secondary. For H2, the primary estimate is `burst/recovery`; the
`sustained` estimate is descriptive because the shared admission rule leaves few in-flight cuts
there.

1. Compute `Y_i(a,c)` for every signal question and arm.
2. Compute the paired difference `Delta(live, fixed4k | c)` and its question-cluster bootstrap 95%
   CI (10,000 resamples, question as the resampling unit). Repeat for the pooled estimate, with
   question as the resampling unit and condition as a fixed block.
3. Report the per-question win/loss/tie table and a paired permutation or sign test on the
   question-level proportions. As a robustness check, collapse each question to a majority-correct
   binary and run an exact McNemar test; the two analyses answer the same question under different
   summaries, and both are reported.
4. Repeat for `live` vs `arrival`, using `burst/recovery` as the primary estimate and `sustained`
   as descriptive.
5. Report the same for `live` vs `fixed8k`, with eventual accuracy as the non-inferiority endpoint.

The primary numerator and denominator are printed together. A rate without its denominator is not
a result.

### 8.7.2 Secondary

- Eventual accuracy, deadline attainment, cap rate, missing/error rate, per arm and condition.
- Latency and queue-time distributions (mean, p50, p90, p99).
- Thinking, cue and answer tokens; tokens per correct-on-time answer; GPU-seconds per
  correct-on-time answer.
- Throughput (responses/minute, output tokens/s), goodput per minute, phase wall time.
- Pressure frequency, cuts per phase, progress at cut, cut-to-finish time, cue tokens and controller
  overhead, so the full mechanism is charged.
- Preemptions, KV occupancy, GPU utilisation.
- An accuracy-versus-tokens and accuracy-versus-latency frontier, not only a single winner column.
- Per-question paired changes, not just aggregate totals (the binder's house rule).

### 8.7.3 Heterogeneity and manipulation checks

Pre-registered subgroups: `sustained` vs `burst`; fresh vs exposed; question difficulty band
(published source/level, not observed outcome); progress-at-cut quartile. These are descriptive,
not additional primary tests. Report them with CIs and label them exploratory.

Manipulation checks that must pass before the primary analysis is interpreted:

- Every cut lands exactly at the intended token position; no cut after close; no cut of a
  naturally closed request.
- `arrival` and `fixed` phases have zero in-flight cuts.
- `low` phases have zero pressure events and zero `live` cuts; `arrival` and `live` match `fixed8k`
  within noise, while `fixed4k` may differ because it uses a different budget.
- The waiting-count threshold fires in the pressure conditions and not in `low`.
- The graph and eager cue positions match if graphs are enabled.
- Trace injection lag is below 1 s; coverage is complete; no phase was silently truncated.

If a manipulation check fails, the affected phase is invalid and is not used to support or refute
the hypothesis. It is preserved and reported.

### 8.7.4 Multiplicity and reporting

Three pre-registered comparisons (H1, H2, H3) form the primary family. Holm-adjusted p-values are
reported; the 95% CIs are reported unadjusted and clearly labelled, with the Holm decision stated
next to them. Secondary outcomes are descriptive. No subgroup or threshold sweep is allowed to
become the headline.

### 8.7.5 Missing data and failures

Caps, timeouts, request-level errors and missing outputs are failures in the denominator. Their
rates are reported per arm. A phase with missing records is not "cleaned" by dropping requests; the
planned denominator from the frozen trace is used, and the coverage is reported. A phase that
crashes or loses coverage is invalid and is repeated in full from the frozen trace; the invalid
attempt is preserved but is not used as a policy result. A single request error inside an otherwise
valid phase is a failure, not grounds to rerun the arm.

## 8.8 What would change our mind

- If `live` does not beat `fixed4k` at several hundred responses per arm, H1 is false as written.
  The project should pivot to a different lever or model, not tune the threshold.
- If the accuracy gap against `fixed8k` is stable at 5-10 points rather than about 3, the mechanism
  needs a later, smaller or selective cut before any serving claim.
- If cuts help only before the request has found its route, the useful control variable is
  progress, not queue length; the traffic-only framing is wrong.
- If the effect shrinks as concurrency rises, the old two-slot rig was an artefact; report that.
- If `fixed6k` matches `live`, the simpler static budget wins; report the static result and retire
  the adaptive claim unless it has another measured advantage.
- If the fresh subset and the exposed subset disagree, treat contamination or distribution shift as
  a live explanation and do not pool them into a single headline.
- If a stronger scheduler would empty the queue, the cut has nothing left to do. The main path does
  not run a scheduler-only control, but the fixed arms' realised queue is reported; an empty queue
  under load is a finding about the rig, not a win for the policy.

