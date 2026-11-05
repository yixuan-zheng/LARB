# Week 6 CPU bottleneck audit

Completed November 4, 2026. Scope: identify why saved computation does not increase correct-on-time goodput, then select one falsifiable hypothesis. **No controller was implemented and no GPU job was submitted.**

## Decision

**Savings do reach request slots and waiting requests. Correctness changes cancel the observed deadline benefit.** The logs do not support delayed slot reuse as the main explanation. They also do not yet support deploying a prediction-heavy selective-rescue controller.

The strongest next hypothesis concerns **when admission decisions are made**. A recurring counted live reduction happens at zero generated tokens, after a request has waited since HTTP arrival. Test whether rechecking the budget at actual worker admission explains enough of the apparent live benefit to avoid genuine in-flight cuts. This is a candidate causal explanation, not an effect established by replay. [Selected hypothesis, minimal falsification proposal and stopping rules](DECISION.md).

## Evidence and integrity

Three engine runs: original measured pilot 6777256, plus the two blocks in 6791535. Reconstructed **244 raw requests: 232 measured and 12 probes**, and verified 21 immutable manifest/source-lock/trace/progress/worker/scheduler/summary input files by SHA256. The earlier pilot provides mechanical/context evidence; the **40 live/arrival-only matched cases** from the latest experiment are the primary paired comparison. No denominator changes, favorable extraction corrections, inference retries, or synthetic hybrid grading.

Input paths are defined relative to the repository in extract.py. Sources/archives remain in the original private collections. Original summary fields, per-phase counts and all raw completion contracts were checked against the reconstructed records. Every measured cut's token progress equals its recorded scheduler computed-token position minus prompt length. Same-phase worker/scheduler monotonic times are used; raw process callbacks can straddle an EOS scheduler event by milliseconds, so a negative callback lag is not a physical negative latency.

## 1. What prevents goodput gains: paired accounting

| Matched live vs arrival-only cases | Count |
|---|---:|
| Wrong under both | 23 |
| Correct and timely under both | 8 |
| Correct under both; only live is timely | 2 |
| Correct under both; both late | 2 |
| Correct only under live | 1 |
| Correct only under arrival-only | 4 |

All 40 cases remain included. Live has three goodput gains: **two deadline crossings with both answers correct**, and one correctness gain. It has three goodput losses from changed correctness. A fourth correctness loss is late under both policies and affects overall accuracy without changing the primary numerator. Thus both policies deliver 11/40 correct on time, while overall correctness is 13/40 live vs 16/40 arrival-only.

The two deadline crossings are question 19 in the two burst blocks. They are the same development question under different seeds, not two independent questions. It is uncut and receives 4K at HTTP admission under both policies:

| Block | Arrival queue / service | Live queue / service | Arrival deadline lateness | Live deadline lateness |
|---|---|---|---:|---:|
| 0 | 204.0s / 76.2s | 110.6s / 80.5s | +43.9s | −45.3s |
| 1 | 220.6s / 82.9s | 114.4s / 81.6s | +67.1s | −40.3s |

This directly demonstrates earlier service of useful queued work. It does not identify which subset of earlier cuts is necessary.

### Quality changes are broader than directly cut requests

Two latest cut targets are arrival-correct/live-wrong. One uncut request loses correctness because its HTTP admission budget changes from 8K to 4K as queue history changes (block1 burst question26). Another uncut same-budget request changes correctness while remaining late (block0 burst question21). The one correctness gain is an uncut same-8K request that completes normally under live and caps under arrival-only (block0 near question21).

**Ten of sixteen cut targets already have different token prefixes before their own cut**, and only eight of forty full paired token sequences are identical. Matched seeds do not make these identical trajectories. This is evidence of different executions; it does not identify a numerical cause or prove that the target's own cut caused its quality change. An estimator for “safe donor correctness” alone would miss admission and other-request effects.

## 2. Timing and actual usable slot release

Across all three runs, 105 measured completed-request observations occur with an existing waiting queue. They span **104 distinct scheduler release steps**; every such step schedules at least one prior waiter in the same step. The count is not 105 independent waiter rescues. No preemptions were observed. There is no gross post-completion slot-reuse delay in these logs.

The distinction is that a cut is not completion:

- Across 24 measured cuts, median cut-to-final-completion is **29.1s**, range **14.0–90.5s**.
- Median forced-cue-to-completion is **27.6s**, range **14.0–31.8s**.
- Three cuts occur at zero progress; they still generate to 4K before cueing. Their cut-to-completion spans roughly **84–90s**.
- Four cuts leave less than 1,024 reasoning tokens of 8K headroom (including two with only 110 and 59 tokens left). A generic queue trigger can intervene very late for little reasoning reduction.
- In 14/24 cut-target observations, a waiter begins before that donor finishes, using another lane. This does not make the donor cut useless; it means donor release and next-waiter admission must not be conflated.

These measurements do not justify shortening the answer allowance. Answer tails may contain necessary work; changing them would define a new quality protocol.

### Token savings really reduce scheduled request time

Latest two blocks, 40 measured responses per policy:

| Policy | Mean queue | Mean service after first scheduling | Mean end-to-end latency | Scheduled request-slot seconds inside common horizons |
|---|---:|---:|---:|---:|
| fixed4k | 28.5s | 83.3s | 111.9s | 3,332.4 |
| fixed8k | 81.2s | 136.9s | 218.1s | 5,476.3 |
| arrival | 70.5s | 126.4s | 197.0s | 5,057.8 |
| live | 36.4s | 104.3s | 140.7s | 4,172.7 |

Compared with arrival-only, live reduces mean queue delay **48.4%**, mean service time **17.5%**, and reconstructed scheduled request-slot time **17.5%**. It removes 58,535 thinking tokens but adds 2,077 answer-after-close tokens; net output savings are 56,494 tokens (16.4%). The final-answer phase therefore offsets some saving, not all of it.

Slot-time is obtained by integrating recorded scheduled-request counts between scheduler events, clipped to each fixed observation horizon. It is not kernel busy time, exact resident-request occupancy, hardware utilization, energy, or billed GPU-time savings. Some prefill steps may omit a resident request from the scheduled set. The explicit max_num_seqs=2 cap creates a two-request scheduling limit; this experiment does not establish that physical GPU capacity or KV memory was saturated. No exact free-KV-block trace is available.

## 3. Workload headroom and coordination

Arrivals are finite and frozen; faster execution cannot create new requests. Under this metric, efficiency improves goodput only when it changes answer correctness or moves a correct completion across a deadline/horizon. Ten of twelve both-correct paired cases do not change timely status. Slack/recovery portions leave scheduled slots unused even though the earlier burst queues. Pooled scheduled-slot occupancy within common horizons falls from 59.2% to 48.9%; that is expected from finishing the same finite work sooner, not evidence of worse GPU efficiency.

The admission rule uses the service's queue snapshot at HTTP acceptance. The engine can admit the request much later. A recurring burst request has:

| Run | Provisional HTTP budget | Wait before worker admission | Worker reduction | Generated tokens at reduction |
|---|---:|---:|---:|---:|
| Latest block 0 | 8K | 24.4s | 4K | 0 |
| Latest block 1 | 8K | 30.8s | 4K | 0 |

The original pilot has the same structural zero-progress reduction. In each latest block the provisional HTTP snapshot contains no waiters; the worker snapshot later contains a backlog. Our “live” arm therefore combines genuine mid-generation cuts with a late admission decision that the arrival-only baseline omits. This is the concrete distinction behind H1. It does not show that the entry decision alone is sufficient: 14/16 latest reductions occur after some generation.

## 4. Prediction audit and why the first hybrid gate fails

A simple fixed-lane model uses the corrected heap/lane reuse, recent five-second observed decode cadence, cue contract, and empirical thinking/answer-tail profiles from fixed/arrival policies. It includes final-answer time. Calibration transfers between the two latest blocks; the older pilot is context using the latest profiles. No answer labels, future output lengths of the current request, or actual future completion times are prediction inputs. Closed/cued state reconstruction uses only already-generated prefix information. Client deadlines are available in logs but would need to be forwarded to worker state for a deployed predictor.

Validation is restricted to policies that do not change admitted budgets later, where continuation is observed. To avoid presenting repeated one-second states as independent requests, errors are summarized by each waiting request's median absolute error first:

| Held-out development block | Waiting request/phase cases | Median request error | P90 request error | Worst request median error |
|---|---:|---:|---:|---:|
| 0, timing profiles from block1 | 30 | 9.2s | 34.5s | 75.8s |
| 1, timing profiles from block0 | 30 | 13.0s | 32.2s | 83.1s |

These are cross-block development checks on reused questions, not fresh validation. Median signed errors also differ by block, and answer/early-completion variability remains substantial.

The predeclared sensitivity question is whether a single-cut rescue survives an optimistic no-cut estimate (−25% remaining time) and pessimistic cut estimate (+25%). It finds **zero** robust rescues among 2,650 sampled eligible measured states across all runs. Point estimates find 1, 64 and 80 states in the old pilot/block0/block1, respectively; many are repeated views of the same waiter. At actual live decision snapshots, the only point-estimate rescue in each run is the zero-progress burst request helping the recurring downstream waiter. None survives the sensitivity check.

This is an assumption-sensitive shadow diagnostic, not an upper bound. It ignores future arrivals and coupled future reductions, assumes fixed-lane service and transfers noisy tail profiles. A ±25% bracket is not a calibrated confidence interval. A single-cut gate can miss a benefit requiring multiple coordinated cuts. Accordingly, the result stops **this simple predictor-driven implementation**, not all deadline-aware control. Do not tune the bracket until a preferred result appears.

## 5. Ranked bottleneck assessment

| Explanation | Evidence | Assessment |
|---|---|---|
| Correctness/normal-completion changes offset deadline gains | Three goodput gains and three correctness-related goodput losses; extra late correctness loss | Strong descriptive support; individual decision causality unresolved |
| Admission and running decisions are coupled | Zero-progress cuts recur; three matched HTTP budgets differ; uncut outcomes change | Strong motivation for a clean admission-timing ablation |
| Cue/final-answer work delays donor release | 14–32s cue tails and up to 90s cut-to-completion | Real timing constraint; savings still reach waiters |
| Completed slots are not recycled promptly | 104/104 queued release steps admit a prior waiter immediately | Not supported at observed scheduler granularity |
| A simple deadline predictor can select safe rescues | Large outliers; no sensitivity-robust single-cut rescues | Does not pass the implementation gate |
| GPU/KV efficiency failure is the principal cause | No utilization/global-free-block instrumentation; no preemptions; explicit two-sequence cap | Not established; do not infer from token counts |
| All savings should increase this trace's goodput | Frozen finite arrivals and only some deadline-sensitive correct answers | Unsupported expectation; goodput headroom is limited |

## 6. One next hypothesis and a stopping point

**H1:** Reconsidering budgets at actual engine admission can retain a material fraction of live's burst benefit without interrupting already-running reasoning. The observed stale HTTP decision and recurring zero-progress reduction make this a focused question; sufficiency remains untested.

The minimal clean proposal has three contemporaneous arms: existing HTTP arrival-only, HTTP admission plus one reconsideration at worker entry (then frozen), and full live. Two existing burst/seed blocks give 72 measured requests. Engineering coverage would add at most 14 probes. This is a development attribution test; it is not a fresh quality evaluation or a claim against absent fixed baselines.

Predeclare the entry-only success gate: no fewer correct-on-time answers than full live in either block, no fewer total correct answers than HTTP arrival-only pooled, and at least half of full-live's positive token saving over HTTP-only retained in each block. If it fails, stop this branch rather than sweeping rules. If the baseline contrast or the entry mechanism does not reproduce, label the test inconclusive and stop. All these are descriptive pilot gates, not formal noninferiority claims. [Detailed experiment/resource envelope](DECISION.md).

Implementation and GPU allocation remain unapproved. The next action is review of these findings. A predictor-heavy hybrid and a large five-policy fresh study have not earned immediate execution.

## Related work and limits of contribution

The method comparison in [RELATED-WORK.md](RELATED-WORK.md) separates confidence-based control, phase-aware scheduling and our actual engine-entry distinction. Relevant methods: [LASER](https://arxiv.org/html/2606.31580v1), [PASCAL](https://arxiv.org/html/2602.11530v1), [Dynasor](https://arxiv.org/html/2412.20993v2). No baseline was reproduced and no superiority claim is made. A contribution would require a fair controlled result or a reproducible boundary, followed by fresh validation; generic hybrid similarity is neither a veto nor a novelty claim.

The two latest blocks share one GPU allocation and conflate seed/order/run time. There are only 12 unique measured development questions. Timing states and shared-queue outcomes are dependent. Existing traces cannot reveal the answers or finish times of a controller we did not execute. No counterfactual hybrid accuracy, accuracy oracle, population p-value, or GPU-efficiency percentage is computed.

## Artifacts and verification

- [evidence/audit-summary.json](evidence/audit-summary.json): quantitative bottleneck checks and outcome ledger.
- [evidence/response-metrics.json](evidence/response-metrics.json): 244 derived response records, including every cap/probe; no raw text or private paths.
- [evidence/paired-outcomes.csv](evidence/paired-outcomes.csv) and [budget-paths.json](evidence/budget-paths.json): all 40 matched cases, admission budgets and prefix-divergence diagnostics.
- [evidence/cut-timelines.json](evidence/cut-timelines.json), [release-events.json](evidence/release-events.json), and [phase-summary.json](evidence/phase-summary.json): cut/release/queue evidence.
- [evidence/prediction-summary.json](evidence/prediction-summary.json), [prediction-validation.json](evidence/prediction-validation.json), and [decision-opportunities.json](evidence/decision-opportunities.json): request-level errors and observed-cut opportunities. Large per-second state arrays remain private.
- [analysis/reproduce.py](analysis/reproduce.py): reproduces compact metrics without raw logs.
- [analysis/raw-audit/](analysis/raw-audit/): full CPU reconstruction code, relocated for this package; requires original private collections.
- [VERIFICATION.json](VERIFICATION.json) and [MANIFEST.json](MANIFEST.json): verification provenance and public file hashes.

The original CPU audit verified all 244 records,232 measured rows,40 paired cases and 21 original input hashes, and fully reproduced25 JSON artifacts in separate output. The public compact check reproduces derived accounting; it does not independently repeat token decoding, grading, every scheduler event or timing-profile estimation without the raw evidence. Original inputs and large sampled states are retained privately. No inference or outcome was rerun for packaging.
