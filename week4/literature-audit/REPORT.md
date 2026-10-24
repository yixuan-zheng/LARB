# Prior-work evidence audit and implications for LARB

The purpose of this review is to understand demonstrated capabilities, assumptions and remaining engineering questions. Conceptual overlap does not disqualify LARB. A contribution can come from a useful mechanism, a substantial measured improvement, reliable execution under realistic conditions, an explanation of failure modes, or a combination of those. The comparison needs to establish the added value; it does not require an idea that nobody has mentioned before.

Five full papers were inspected through their algorithms, experimental sections, relevant appendices and rendered figures/tables. The public P-PAS+ numerical artifacts were independently aggregated without running its benchmark. ACER remains an abstract-only access gap, explicitly separated below. This is a targeted evidence audit, not a claim to have exhausted the literature, certified proofs or reproduced the competing systems. No controller was modified and no GPU job was submitted.

[Source versions, file hashes and visual inspection coverage](sources.json). [Arithmetic verification](verification.json). Earlier [LASER interface investigation](../laser-feasibility/REPORT.md) and [Dynasor code audit](../evaluation-plan/upstream-audit.json) remain complementary evidence.

## 1. LASER: useful adaptive reasoning evidence, unresolved serving semantics

**Paper evidence.** [LASER v1](https://arxiv.org/html/2606.31580v1), Algorithm 1/Eqs. 5-8, uses an active-load EMA to adjust a confidence exit threshold; prompt length and load set the initial chunk budget. Two models/four benchmarks use RTX 4090 inference measurements and FIFO discrete-event serving simulation. Comparators are Vanilla, NoThinking and fixed confidence thresholds 0.95/0.90, not fixed token caps. Table 2 Qwen burst: Fixed-High 163.9 s/12.0% SLO, LASER 133.7 s/17.6%. Figure 4 DS ablation:

| Variant | Accuracy (%) | Mean latency (s) | Throughput (QPS) |
| --- | ---: | ---: | ---: |
| Baseline | 88.2 | 638.1 | .320 |
| Threshold only | 86.2 | 668.6 | .317 |
| Budget only | 85.0 | 490.2 | .369 |
| Combined | 86.4 | 513.2 | .377 |

Table 1 labels DS QPS=2 latencies 167.9/130.0 s instead. The paper specifies active count, target 10, a 30 s SLO and Poisson rates 0.5-8; probe confidence is evaluated at linguistic transitions. Figures 3/4 and Tables 1-3 were visually inspected (PDF pp.8-10).

**Our assessment and questions.** The ablation gives a more useful lesson than a generic statement that load-aware exit works. Relative to budget-only, the combined method trades about 4.7% more latency for 1.4 points of accuracy and slightly greater throughput. Its threshold-only arm is worse on all three displayed measures than the baseline. This supports distinguishing budget reduction from the incremental contribution of adaptive confidence. It does not establish that the threshold component is useless in every workload.

The different latency scales in the main table and the similarly labeled ablation need an explanation before treating them as one internally matched result. Different configurations or measurement windows could explain them; the inspected description does not resolve that. The source numbers are retained separately, rather than silently reconciling them.

There is also an important load-definition question. If the stated single-server FIFO simulation means one active inference at a time, an active-count target of ten cannot produce the advertised overload response. It might instead count outstanding logical requests or model another concurrency semantics. We cannot decide which interpretation the implementation uses from this description. Likewise, the lowest offered rate exceeds several reported completion rates. Finite overloaded experiments are legitimate, but warm-up, drain, measurement horizon, drops and stability need specification before interpreting them as steady serving performance.

Latency-SLO attainment and overall accuracy are reported separately; the inspected tables do not supply the joint correct-final-answer-before-deadline metric we use. We should not compare their SLO percentage directly to our correct-on-time percentage.

The constant-time threshold arithmetic is not the same cost as a complete probe/rollback/final-answer path. The fixed-threshold comparators already probe, so the incremental scalar controller may indeed be cheap. A comparison with a nonprobing token-budget policy still needs to charge the entire probe path. Our earlier CPU investigation identifies concrete runtime choices that the mathematical policy alone does not resolve.

**Implication for our path.** Keep simple token-budget allocation as a serious competitor to confidence control. A real concurrent implementation with complete call/cue/answer accounting could deliver useful additional evidence, even with a related high-level idea. That would become a substantive contribution through measured performance and explanatory ablations, not merely by replacing simulation with a runtime. LASER's incomplete specification leaves comparison work to do; it does not prove LARB superior.

## 2. Dynasor/Certaindex: substantial systems evidence with separable sources of gain

**Paper evidence.** [Certaindex v2](https://arxiv.org/html/2412.20993v2) probes CoT for answer stability and combines adaptive allocation with gang/SJF scheduling. Figure 6 reports 11-29% CoT token savings at matched accuracy. Figure 8's online workloads are SC/MCTS/Rebase, not its single-chain CoT setup. A100 hardware is used; MCTS/Rebase use a separate reward-model GPU. Appendix F constructs difficulty-dependent deadlines using extensive trial runs. Component figures:

| Location | Comparison | Reported result |
| --- | --- | --- |
| Fig.18, SC/GSM8K | Uniform LPM / uniform gang | 410 / 306 s |
| Fig.18 | Adaptive LPM / gang / SJF | 165 / 159 / 134 s |
| Fig.19, SC/MATH | Uniform LPM / adaptive LPM / adaptive SJF | 1.0 / 1.2 / 1.9 times sustainable rate |

Appendix D profiles labeled calibration data; Appendix E assumes eventual distributional stabilization. Figure 8 and Appendix F/G figures were inspected visually (PDF pp.9,26-27). Earlier pinned public-helper discrepancies are documented separately, not substituted for a system evaluation.

**Our assessment and questions.** This is substantive evidence of efficient reasoning and an integrated system, and should be treated as such. It is also an example of how useful systems contributions can combine existing ideas rather than depend on conceptual exclusivity.

The component breakdown prevents two opposite mistakes. We should not attribute every online gain to certainty, but we should not dismiss its allocation mechanism as merely a scheduling artifact. The first displayed workload benefits substantially from allocation even under the same LPM scheduler; in the second, much of the final increase comes from adding SJF. A local comparison needs to choose which component it tests.

A probe's stable answer is not necessarily a correct answer. The theory concerns conditions under which continuation changes the answer distribution little; it is not an unconditional certification that a short stability window is safe on every request. Calibration and finite-window reliability remain empirical matters. In particular, preserving total accuracy can conceal which requests lose useful reasoning.

The deadline construction is a workload design choice, not evidence of inference-time label leakage into the controller. It nonetheless means deadlines encode prior knowledge about difficulty. Our evaluation should distinguish externally supplied deadlines from such oracle-informed workloads. The reported online SLO curves cannot be transferred directly to a two-slot, single-chain setting with outcome-independent deadlines.

The earlier helper audit is a narrow implementation concern. Repairing a public helper would not show the full paper invalid, and its complete scheduler's results cannot be inferred from our tiny CPU cases. Full integration also has engine-version and cache assumptions to account for.

**Implication for our path.** LARB can investigate the usefulness of direct, nonprobing intervention under uncertain traffic while measuring the quality cost it accepts. It can also eventually combine pressure with a progress signal if evidence justifies that. We need not promise a novel confidence statistic or reproduce every multi-path program before developing our own controller. If we claim that a new allocation mechanism helps, retain fixed scheduling in the core comparison and ablate scheduling improvements separately.

## 3. P-PAS/P-PAS+: a reproducible example of useful adaptation with modest gains

**Paper evidence.** [P-PAS v2](https://arxiv.org/html/2608.15171v2) switches the scheduler's per-iteration token budget using prefill/decode pressure, not reasoning depth. P-PAS+ adds residual prefill work. Figures 3/4 show switching and a regime crossover; Table 8 compares static sweeps. Appendix 10.5 defines six dynamic conditions/model. Public artifacts are pinned at [3f0fd3e](https://github.com/TimoSaemann/ppas-vllm/tree/3f0fd3eb348b818224d5bc75351e2e6fb66a044c).

| Model | Best tested static MBT | Mean-latency gain recomputed | Faster matched requests |
| --- | ---: | ---: | ---: |
| Qwen3.8-27B | 768 | 3.0221% | 445/488 |
| Nemotron-30B | 1,280 | 3.0534% | 925/1,045 |

The aggregation averages condition-level ratios after averaging seed runs. Qwen logs have seeds 0-9; Nemotron 0-10, although the appendix specifies eleven for each. The inspected benchmark uses synthetic token-ID prompts, fixed output lengths and ignored EOS; newer experiments use vLLM 0.27.1. Figures/tables were visually inspected (PDF pp.5,9-10).

**Our assessment and questions.** This is the strongest arithmetic reproduction in this audit. Every published matched-request count above agrees with the logs. Logical arrivals and requested lengths match across compared policies, and all logged runs report success. The seed-count discrepancy is a documentation issue, not a reason to discard the numerical result; the available Qwen data reproduce the reported gain.

Several lessons support our independence rather than constrain it. A small mechanism can be worth studying when its operating conditions, best alternatives and costs are clear. Comparing only the two controller endpoints would be insufficient: an intermediate static setting can absorb most of the benefit. The table and artifact sweep make that possibility inspectable. The mean gain is modest despite most individual requests being faster; those statements answer different questions and should not be conflated.

Its synthetic construction deliberately controls service shape. That is reasonable for scheduler characterization, but provides no evidence about answer quality or the value of additional reasoning. A configured generation length is not equivalent to a budget that can change a model's correctness. Also, its scheduling choice is reversible at the next iteration; a reasoning cutoff is not. We should not assume a successful switch-back design can restore reasoning already stopped.

The implementation inspected here is on a newer engine than our frozen vLLM 0.11.2 environment. Similar configuration names do not establish compatibility, and the two kinds of token budgets must not be mixed. No upstream benchmark or model code was executed for this audit.

**Implication for our path.** Adopt the evidence standard: demonstrate where adaptation has useful room to improve, include intermediate static controls, and preserve mixed-regime traces. We do not need to adopt its pressure function, hardware regime, or binary controller. Our unresolved quality/serving interaction is an additional empirical dimension, not a claim that P-PAS tried and failed to solve it.

## 4. UniBoost: stronger tail performance can coexist with worse mean performance

**Paper evidence.** [Beyond Prediction / UniBoost](https://arxiv.org/html/2606.18431v1), also in [PMLR](https://proceedings.mlr.press/v306/li26n.html), uses unified priority boosting, KV-aware preemption hysteresis and online tail statistics. Evaluation includes A100 serving, Llama/CodeLlama/Qwen, 10,000-request workloads, Azure arrivals and reasoning/chat mixtures. Prefix/radix caching is disabled in the main controlled study. Table 2, relative to perfect-length TRAIL+, reports:

| Metric | Displayed improvement | Meaning under the table's convention |
| --- | ---: | --- |
| Mean completion latency | -19.1% | Worse |
| P99 completion latency | +35.1% | Better |
| Mean inter-token latency | -25.3% | Worse |
| Throughput | +1.2% | Better |

Figures 4-8 and the setup/table were inspected (PDF pp.6-8); Appendix A was checked for qualifications. The official project page's Code link resolves back to the project page in this inspection; a usable implementation was not verified from that link.

**Our assessment and questions.** The gains support a tradeoff, not universal latency dominance. Better tail performance can be a valuable contribution even when means worsen, provided that cost is explicit and appropriate to the application. A claim to beat a perfect-length policy is also relative to that policy's objective and implementation; it does not mean beating an oracle optimal for every latency or quality objective.

This is a scheduling result. Keeping the same work but changing its order differs from changing how much reasoning work a request does. Neither a faster first token nor improved tail latency necessarily implies more correct completed answers before deadlines. Conversely, a LARB gain could disappear if a stronger scheduler already removes much of the queue cost; that is a future robustness question, not a prerequisite for implementing any improvement.

The observed degradation is useful when setting our own objective. We should report mean, tail, correctness, deadline success and tokens together, and state which tradeoff the application values. A scalar objective should not silently change from one experiment to the next. Its memory-aware hysteresis is also not automatically the right approach for an irreversible reasoning stop: preemption can resume work, while a forced conclusion cannot recover the discarded continuation.

**Implication for our path.** Keep scheduling and reasoning control distinct in the first ablations. Later, a matched stronger-scheduler control can ask whether an improved LARB mechanism adds value on top of better queue service. We should not dismiss prediction or add a new predictor merely because this paper favors a prediction-free mechanism; local uncertainty and measured cost should decide.

## 5. Queueing-aware allocation: a useful model with a narrower operational contract

**Paper evidence.** [Queueing-Aware Optimization v1](https://arxiv.org/html/2601.10274v1) optimizes fixed per-task token budgets under Poisson arrivals, known task proportions, FIFO M/G/1 service, affine service time and saturating accuracy. Qwen3-8B/A100 measurements fit six task types using 250 instances/budget and three runs; queue simulation uses 10,000 queries, arrival rate 0.1 and accuracy weight 30. Table I allocations are GSM8K 340.5, BBH 345.0, ARC 30.1 and zero for AIME/GPQA/CRUXEval. Figure 3 compares uniform 0/100/500 with the optimized allocation; Figure 4 peaks near GSM8K 340. Table I/Figures 3-4 and setup were visually inspected (PDF pp.6-7).

**Our assessment and questions.** The useful insight is the relationship between individual computation and system delay, including service-time variability. The numerical optimum is conditional on a chosen utility, fitted response curves and a stationary mixture. It is not a deployable universal recommendation to give some tasks no reasoning, nor evidence that a live queue controller has already been solved.

A type-specific static allocator would be a meaningful comparator if our future method uses task labels or offline difficulty estimates. The same information should be available to its baseline. Today our controller does not use those labels, so implementing this optimizer immediately would answer a different question and consume work without isolating our current mechanism.

The fitted monotone accuracy shape can miss overthinking or irregular quality changes. Continuous batching also changes the relationship between token allocation and service time. These are questions to investigate empirically, rather than reasons to reject a tractable model.

The mathematical qualifications matter. Uniform global derivative bounds require a utilization margin below instability; integer rounding should be checked against that margin. The paper includes such stability conditions in its bounds. Importing its optimality or convergence claims into a runtime with unknown arrivals, changing batch sizes and irreversible online decisions would require a separate argument. No independent proof certification was performed here.

**Implication for our path.** Use the model as a way to formulate marginal benefit and congestion cost, not as a command to adopt its optimizer. Our saved traces can test which assumptions are reasonable and where a simple model fails. An explanatory empirical contribution can be valuable even without a new queueing theorem.

## 6. ACER: an unresolved access gap, not an adverse novelty verdict

The [official record](https://theses-dissertations.princeton.edu/entities/publication/2d46f9cc-4422-4d22-aa42-2e80ebd5b46f/full) labels the thesis restricted. The linked download remained inaccessible, and a targeted exact-title/author search did not locate a verified alternative full text. Only the public abstract is assessed: it reports up to +10.5 percentage points accuracy, up to 38% tail-latency reduction at matched accuracy and 21% goodput improvement, with remaining-latency-based control across four configurations.

Those are author-reported claims, not audited results. We have not inspected its figures, models, baselines, cost accounting, deadline construction or detailed algorithm, and cannot assert that any particular mechanism is absent. This access gap should remain explicit. It should not freeze LARB or justify describing deadline-aware work as unavailable to us. If an accessible copy becomes available, inspect it against the same evidence questions; no author contact was initiated.

## 7. What this means for LARB's research direction

The useful conclusion is that several substantial capabilities remain to be demonstrated **together in our target setting**: useful quality, timely completed answers, low control cost, realistic concurrency, and behavior across changing demand. This audit is not proof that no other system supplies that combination. It gives a concrete way to evaluate the added value of our mechanism without using conceptual overlap as an exclusion rule.

There are several legitimate routes to contribution:

| Route | What would make it substantial | What would be insufficient |
| --- | --- | --- |
| Effective lightweight mechanism | Better quality/deadline/compute operating points against well-calibrated static budgets and appropriate adaptive controls | Beating only our original threshold |
| Runtime and cost result | Demonstrate that a reproducible nonprobing intervention achieves useful gains once full auxiliary costs and final answers are charged | Claim novelty merely because a simulator was replaced |
| Decision-quality improvement | Identify when stopping, continuing or choosing another active request creates measurable benefit across independent cases | Explain one selected request and hard-code its lesson |
| Generalizable characterization | Establish when static-short suffices, when longer reasoning helps, and why pressure/slot count/deadlines move the boundary | A few favorable examples or a negative result presented as a universal law |

These routes can reinforce each other. They do not require a wholly new conceptual primitive, a theoretical guarantee, or winning every metric. They do require a meaningful result and a clear account of when and why it holds.

### How the review changes the immediate plan

The one-waiter ablation remains a sensible minimal diagnostic; its role is to test the observed trigger blind spot, not serve as the final research framing. The existing [offline diagnosis and proposed development experiment](../baseline-controls/diagnosis/REPORT.md) remain a proposal, with no implementation or execution authorized by this review.

We should make the quality-versus-budget opportunity and the threshold repair co-primary questions. On an outcome-independent cohort, measure whether extra reasoning yields useful correctness under slack, while a changing exogenous workload tests congestion response. Longer reasoning need not benefit every question; the controller must justify the aggregate benefit against latency and compute cost. If the current model/distribution shows little benefit, that is a scoped finding. It can justify examining another application-driven model/task mix, with its selection rationale fixed before outcomes, rather than abandoning the general problem or selecting only successful questions.

Keep fixed-2,048 and fixed-4,096 in the next focused comparison. Before a stronger claim about all static alternatives, expand a development-only static sweep, freeze selection independently and test the selected static choice on fresh workloads. An offline best-static-per-trace number can be a diagnostic bound, but it has information an online policy does not and should be labeled accordingly.

Do not automatically add persistence, a deadline guard or progress probes. If transient queue spikes cause observed quality losses, persistence has a mechanism to address. If requests miss their own deadlines without queueing, a cue-and-answer reserve guard is justified to investigate. If longer reasoning has value concentrated in states we cannot distinguish cheaply, progress signals become relevant, with their full costs charged. These choices come from our measurements; the literature supplies hypotheses and comparison standards.

A later matched confidence-based adaptation can be useful, but engineering a distorted reproduction is not a prerequisite for every LARB revision. First decide which scientific question that implementation would answer and whether its semantics can be matched. Conversely, do not imply superiority to LASER, Dynasor or ACER without a defensible comparison.

### Workload and evidence that would strengthen the contribution

Use an application-motivated question distribution and a predefined mixture of isolated/slack, sustained pressure and slack-to-burst-to-recovery demand. Keep questions independent of outcomes and rotate them through traffic positions. Inspect actual queue occupancy, not just nominal arrival-rate labels. Use several slots/load levels later to test whether the mechanism depends on one arbitrary concurrency boundary.

Report the joint correct-final-answer-by-deadline outcome, eventual correctness, client latency tails, total generated/auxiliary tokens, computed prefill, queueing, calibration cost and controller overhead. Preserve wrong, late and capped results. Probe-based competitors should share an engine/resource envelope and pay for discarded work; nonprobing LARB should also have its own overhead measured rather than called free. Use application-fixed weights or condition-wise tradeoffs; do not pool favorable regimes after seeing scores.

The research decision is whether a mechanism produces substantial useful improvement over these fair alternatives and whether the study explains its scope. A similar high-level idea does not decide that question. Neither does a competitor's venue, a headline speedup, or the absence of a paper that uses precisely our wording.

## Handoff and remaining gaps

Completed: five targeted full-paper/figure inspections; ACER access recheck; pinned P-PAS code read; independent public-log aggregation with request matching; comparison implications. No third-party full papers/logs are vendored. No model inference, GPU work, controller change or third-party executable code was run.

Remaining: ACER full text; independent executions of prior systems; exact LASER simulation/load and ablation-scale semantics; isolation of probe costs in our runtime; static-budget opportunity across a broader outcome-independent cohort. No author correspondence or upstream reports have been sent. The recommended next action is to agree on the local mechanism question and evidence standard, then freeze a bounded development design if proceeding. This is a research map, not a requirement to follow every paper's architecture or reproduce every baseline at once.
