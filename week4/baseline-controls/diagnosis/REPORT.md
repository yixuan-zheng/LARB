# Where current live LARB falls behind fixed-2,048

The strongest trace-supported limitation is a **queue threshold blind spot**, rather than slow control delivery. The policy permits a 16,384-token budget whenever fewer than two requests wait. A running request can therefore continue long thinking with one request queued, and can remain long at the tail of a workload after queue pressure subsides. On these traces, that additional thinking produces no observed correctness gain over fixed-2,048. This supports testing a one-waiter trigger before adding predictors, confidence probes, or deadline machinery.

This is an offline descriptive diagnosis of the two completed comparisons, not a controller implementation or a simulated result for a new policy. The [machine-readable diagnosis](diagnosis.json) contains all 48 live/fixed question-block pairs, worker decisions, latency decomposition, sampled scheduler queue integrals and input hashes. [The script](diagnose.py) reads only saved records. The earlier [final comparison report](../REPORT.md) remains the source for the complete four-policy tables and byte-for-byte grading verification.

## Questions 1 and 94

Question 1 is the double-series problem whose answer is `p - q`. In block 0, both policies generate exactly the same first 2,048 tokens, including reasoning toward that answer. Fixed-short then forces the unchanged answer cue; live continues checking the same derivation and eventually gives the same correct answer.

| Traffic, block | Policy | Queue wait (s) | Completion from arrival (s) | Thinking tokens | Correct / on time |
| --- | --- | --- | --- | --- | --- |
| Sustained, 0 | Fixed-2,048 | 34.99 | 77.09 | 2,048 | Yes / yes |
| Sustained, 0 | Live | 36.84 | 127.33 | 5,602 | Yes / no |
| Late burst, 0 | Fixed-2,048 | 165.80 | 206.49 | 2,048 | Yes / no |
| Late burst, 0 | Live | 166.25 | 275.63 | 6,483 | Yes / no |

For sustained block 0, live is admitted with **one waiter** and never reaches the two-waiter trigger while thinking. It spends 81.89 seconds from worker admission to thinking closure, versus fixed-short's 31.90 seconds. Of the 50.24-second completion difference, only 1.85 seconds is additional queueing. This is primarily a service-time overrun, not an inherited queue delay. The deadline is 95.03 seconds. Extra checking yields no observed quality improvement and loses an on-time answer.

The burst version is already beyond its 96.89-second deadline before admission; forcing short can reduce tail cost, but cannot retroactively make that request on time. It adds 4,435 thinking tokens and 69.14 seconds to completion with the same correctness. Question 1 in block 1 is short under both policies in burst, and live is cut early under sustained pressure (460 tokens at decision, final thinking 2,048); both policies then succeed on the sustained deadline.

One waiter does not automatically mean large downstream harm. In sustained block 0, the final queued question 77 waits 35.04 seconds under live versus 35.45 under fixed-short and completes in 57.23 versus 57.84 seconds. The other slot frees up. Thus question 1's long tail clearly hurts its **own** deadline and token use; these records do not support attributing a large delay to question 77.

Question 94 is a geometry question supplied as text with Asymptote drawing code. Several outputs spend thinking on drawing coordinates that conflict with labeled geometric angles; this makes its behavior worth retaining as an input-representation and reasoning failure case, without changing the prompt after seeing the outcome.

| Traffic, block | Policy | Thinking / answer tokens | Completion (s) | Extracted answer | Graded correct |
| --- | --- | --- | --- | --- | --- |
| Sustained, 0 | Fixed-2,048 | 2,048 / 1,028 | 70.07 | 80 degrees | Yes |
| Sustained, 0 | Live | 2,048 / 839 | 64.34 | 130 | No |
| Sustained, 1 | Fixed-2,048 | 2,048 / 821 | 42.28 | 130 | No |
| Sustained, 1 | Live | 2,876 / 1,026 | 58.42 | 25 | No |

In sustained block 0, live reduces its budget at token **591**, well before the cutoff, and both policies ultimately force the same cue at 2,048. Their output prefixes diverge at token offset **124**, before the live decision, despite identical prompts and seeds. This is consistent with serving/sampling trajectory differences under different batching; the traces do not identify the exact numerical cause. The correctness loss cannot be identified as the effect of a shorter budget, because the realized budgets are equal. Manual reading also finds the fixed-short answer's final justification weak: the grade is correct, but one successful sample does not demonstrate reliable geometric reasoning or an ideal cutoff.

In sustained block 1, live reaches the two-waiter trigger only at **2,876 tokens** (42.77 seconds after admission). It immediately begins the cue there: the 828 tokens beyond short have already been spent and cannot be recovered. It finishes 16.14 seconds later than fixed-short and remains incorrect. In the burst, both policies have identical complete token sequences for question 94 in each block and are incorrect (51 in block 0; 129 degrees in block 1). More reasoning is not demonstrated to fix this case. Admission's occasional correct result and live's errors should remain visible as sample variability, not motivate a question-specific exception.

## Late cuts, nonbinding updates and additional reasoning

All four late-burst live updates occur early, at 436–448 tokens, with pressure snapshots 1.94–2.64 ms old. They bind at 2,048 as intended. There is no evidence that the live transport path is late in this condition.

Under sustained pressure, **three of 15 updates arrive after the short budget has already been exceeded**:

| Block / question | Tokens at decision and forced cue | Tokens already beyond 2,048 | Seconds after admission | Correct under fixed-short / live |
| --- | --- | --- | --- | --- |
| 0 / 83 | 2,537 | 489 | 42.67 | Yes / yes |
| 0 / 89 | 2,130 | 82 | 34.37 | Yes / yes |
| 1 / 94 | 2,876 | 828 | 42.77 | No / no |

These total **1,399 already-spent tokens** beyond the static cap. Snapshot ages are about 2–3 ms, pointing to the pressure criterion rather than stale delivery. This is not a prediction that a different trigger would reproduce the fixed-short trajectory; earlier cuts can change all subsequent batching and text.

Five sustained updates are nonbinding: block 0 questions 28/42/65 and block 1 questions 65/77. Their live thinking closes naturally at **1,921 / 1,374 / 1,263 / 985 / 1,149 tokens**, all below 2,048. The metadata updates do not truncate generation. Calling their entire reasoning cost waste would be incorrect; suppressing these updates would mostly remove small control overhead, which was not separately benchmarked. There is no trace-supported case for an early-exit predictor just to avoid these updates.

Relative to fixed-short, live has more thinking in **one burst pair** (question 1, block 0: +4,435 tokens) and **eight sustained pairs** (+5,583 positive differences). None produces a correctness gain. Sustained positive differences include questions 83 (+489), 89 (+82), 28 (+331), 65 (+209), 77 (+2), 1 (+3,554), 94 (+828) and 42 (+88), with blocks in the saved table. Some pairs use fewer tokens, making the sustained **net thinking increase 3,796**, not 5,583. Differences below the cap can arise from naturally different sampled trajectories, not intentional budget extensions. “No observable benefit” here means no paired correctness improvement on this cohort, not proof that those tokens are universally useless. One such pair completes sooner because its queue wait is shorter.

## Queue and completion behavior

| Traffic | Mean queue wait: fixed / live (s) | Sampled queue area: fixed / live (request-seconds) | Median completion: fixed / live (s) | Output tokens: fixed / live |
| --- | --- | --- | --- | --- |
| Late burst | 83.99 / 85.93 | 2,015.58 / 2,061.87 | 118.77 / 119.68 | 53,793 / 58,388 |
| Sustained | 18.51 / 22.82 | 443.94 / 546.96 | 50.81 / 59.35 | 53,815 / 57,537 |

Queue area integrates consecutive scheduler waiting snapshots; client/worker receipt-based queue waits are reported separately. Small boundary/prefill differences mean these measures need not match exactly. Live's sustained queue area is **23.2% greater** than fixed-short, versus **2.3%** in burst. Summed receipt-based waiting is 103.43 request-seconds greater under sustained pressure and 46.50 greater under burst. Both pressure relief and later admission decisions feed back into the entire queue trajectory.

In sustained live blocks, there are **85.14 and 62.82 seconds** with exactly one waiter and at least one still-thinking active request retaining a long budget. These are durations per block, not multiplied by active requests, and include generation below 2,048. They expose opportunities for an earlier pressure signal; they are not estimates of avoidable delay. The diagnostic does not replay a changed controller or assign hypothetical answers/service times.

## Smallest justified candidate

Test **one-waiter pressure**, changing the shared pressure threshold from two waiting requests to one for admission and live updates. Keep long/short budgets at 16,384/2,048, retain irreversible reductions, preserve the exact cue and answer cap, and keep stock FIFO scheduling. In the current implementation this is a single threshold parameter used by both decisions; changing admission alone would leave running requests exposed when the first waiter arrives.

The rationale is narrow: react when a request first loses immediate service, rather than waiting for a second queued request. This directly covers question 1's observed admission state and may reduce overshoot before short cutoffs. It preserves long reasoning while no request waits. It does not predict difficulty, inspect answers, use question identities, cancel late requests, or assume a future arrival rate. The proposal is an engineering ablation, not itself a novelty claim.

Risks are substantive: one transient waiter can trigger an irreversible cut even when another slot is about to finish; earlier cuts can hurt quality; already-spent thinking cannot be recovered; a single long request with no waiter can still miss its own deadline. A deadline-reserve rule might later address the last limitation, but it would add service estimation and answer-time assumptions that these traces have not yet justified. Do not combine that change with this first test or tune several thresholds against the same small cohort.

## A discriminating development experiment (proposal only)

Use **four policies**: fixed-2,048, fixed-4,096, unchanged live with threshold two, and the one-waiter candidate. Admission-only is already characterized; retaining unchanged live isolates the threshold change. Keep model, runtime, slots, seed schedule, cue, cap, and scoring identical to the saved campaign.

Select **24 additional development questions by SHA-256 ranking of ASCII `week4-onewait-dev-v1:INDEX` (ties by integer index)** from exposed indices 0–99, excluding the current comparison, calibration and mechanics-gate indices. Publish the exact eligible set, salt and cohort before inference. Do not select by correctness, length, geometry failures or estimated need for long reasoning. Use all selected questions under all policies. Keep the 24-question 5C cohort and the other provisionally unused questions outside this development work; any eventual confirmation needs an exposure audit and a fresh frozen holdout.

Two predeclared blocks rotate question positions and reverse policy order; rotate the starting policy across conditions so position counts differ by at most one across the six condition/block cells. Publish the six exact orders before execution. Use a second predefined seed schedule in the second block rather than treating repeated deterministic labels as independent evidence. Two seeds are only a limited variability check. Three conditions yield **576 measured outcomes**:

1. **Isolated requests as a quality diagnostic.** Drain between requests, with each request's deadline measured from its own scheduled arrival. This explicitly tests what extra reasoning buys without queue interference. Use a generous fixed deadline, such as 4S, where S is the frozen exposed-only full-budget calibration unit. This condition has policy-dependent total duration, so report paired quality and per-request latency/tokens; do not compare wall-clock goodput as if it were a matched exogenous traffic trace.
2. **Sustained pressure.** Reuse the predefined 0.3S arrival spacing and 2S relative deadline for every policy. This tests whether the one-waiter rule closes the efficiency gap to fixed-short and improves on unchanged live without losing quality. Publish all outcomes even if the candidate is worse.
3. **An exogenous transition trace.** For example, eight arrivals spaced 2S apart, eight spaced 0.3S apart, a fixed 4S recovery gap, then eight spaced 2S apart, with one 2S relative deadline throughout. Freeze exact timestamps and boundaries before execution. Rotate question-to-position assignments between blocks so no question is permanently assigned to a favorable regime. Analyze observed queue occupancy as well as nominal phases: sparse arrivals do not guarantee slack if a long request persists. Do not postpone arrivals until the candidate drains or otherwise give it policy-specific recovery time.

Use the same exposed-only calibration rule and common frozen traffic across policies within a condition. Keep one allocation per traffic condition so policy comparisons share hardware/calibration. Stage CPU/mechanics verification before those allocations; continuation depends on valid mechanics, complete records and the predeclared compute fit, never favorable accuracy. Estimate a realistic allocation from the saved service distributions and all 576 outcomes, including isolated long reasoning; the 1.38 hours for the earlier two comparisons is an input, not a reliable forecast for this larger design. Freeze the final compute cap and manifests only if execution is subsequently authorized. No new jobs have been submitted.

Primary questions and decision rules should be frozen before inference:

- **Does the threshold repair work?** Candidate versus unchanged live: correct-on-time, eventual quality, queue wait, overshoot tokens and trigger timing. Candidate versus fixed-short: preserve pressure efficiency and expose every quality/deadline loss. Report question/block pairs, all outputs, and both latency tails and token totals.
- **Does adaptivity add value?** Seek an actual quality/on-time gain over fixed-short during slack or transitions, while approaching its congestion performance. Compare fixed-4,096 too, so an intermediate static budget cannot silently explain the gain. Report each condition and transition segment separately; a pooled score must use a traffic mixture fixed in advance.
- **What would stop the claim?** If longer reasoning produces no reproducible quality advantage on the outcome-independent cohort, or the candidate keeps losing deadline success without compensating quality value, these results do not establish adaptivity's application value. Keep fixed-short as the practical baseline; do not rescue the claim by extracting only favorable questions or changing mixture weights after scoring. A small positive development result calls for independent confirmation, not a population guarantee.

The sample is intended to discriminate mechanisms and identify whether a quality/efficiency tradeoff exists, not certify a precise population improvement or noninferiority margin. Choose any application-specific accuracy tolerance and minimum useful gain before the experiment, using the actual deployment requirements; none has been inferred from the current 12-question data.

## What workload could establish adaptivity's value fairly?

Adaptivity needs two properties **together**: some randomly encountered requests benefit from more than 2,048 thinking tokens when capacity and deadlines permit, and unpredictable congestion makes always-long processing expensive for other requests. A representative, outcome-independent stream with slack-to-burst-to-recovery transitions can expose that tradeoff. A permanently congested stream of questions already solved reliably at 2,048 naturally favors fixed-short; a permanently idle stream can favor a static long budget. Neither alone establishes the need for adaptation.

A fair demonstration uses a declared source distribution (or all available development questions), independently generated arrivals/deadlines, rotated/randomized assignments and preset mixture weights. Analyze whether the sampled cohort actually contains a repeatable long-budget quality benefit, rather than labeling particular questions “hard” after observing their answers. If it does not, report that result. A future broader or harder application distribution may be justified by the target use case, but should be chosen for that reason before measuring policy performance. The current traces cannot establish that such a workload exists for this model/dataset, and this proposal does not assume it will.

No literature claims, new inference, controller edits or scheduler changes are needed for this diagnosis. The next decision is whether this minimal ablation and workload design are worth implementing and running.

Verification note: all 48 paired request hashes, shared prompts/seeds and latency decompositions were checked. The frozen deployment README had acquired post-run status notes in the preceding assessment; it has been restored from the executed snapshot so the original source-lock preflight remains reproducible. Current findings and navigation live in the reports, Week 4 README and handoff. No scientific source lock was rewritten.
