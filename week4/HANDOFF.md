# Current Week 4 handoff

## Week closed: start here

Week 4 is complete and packaged. No campaign jobs are active, no results await collection, and no controller revision or new GPU campaign has begun. The [actual checkpoints](CHECKPOINTS.md) record both completed work and deliberate deferrals. [Next-week options and recommendations](NEXT-WEEK.md) give the incoming lead a concrete starting point, with evaluations and tradeoffs.

We went beyond the original route: after real concurrency validation and held-out admission/live testing, we added strong static-budget controls, offline cut/queue diagnosis, and a deeper literature/artifact audit. This changed the research question from whether live beats admission to when adaptive reasoning earns useful value over a strong static choice.

The held-out study supports a load-dependent live benefit: pressure correct-on-time **39/96 → 51/96**, with equal overall eventual correctness but one pressure quality loss. The later development controls challenge the current policy: fixed-2,048 matches live in burst and beats it under sustained pressure, with fewer tokens. These cohorts and claims remain separate. A one-waiter ablation is proposed, not implemented. LASER CPU/interface feasibility is documented; serving integration and a prior-method GPU comparison were deliberately deferred.

The recommended next step is a bounded development study that tests the minimal trigger change and measures the quality-versus-budget opportunity together, retaining fixed-2,048/4,096. Further options include deadline reserves, persistence, intervention selection, progress signals, stronger scheduling controls and an application-motivated broader workload. Similar ideas in prior work do not disqualify these routes; contribution depends on useful capability, substantial measured improvement and sound evidence.

## Evidence and limits

- The reserved campaign contains six matched jobs, 288 measured outcomes and 12 excluded calibration requests, on **24 unique questions** repeated across conditions and blocks. All mechanical/provenance audits pass. [Aggregate](reserved-validation/analysis/summary.json), [paired diagnostics and exposure ledger](reserved-validation/analysis/assessment.json).
- The original development experiment used 12 exposed questions twice: live 12/24 versus admission 8/24 correct on time. Keep it separate from the reserved evaluation. The real concurrency gate passed 176/176 checks. [Development evidence](step1/README.md).
- The bootstrap is descriptive question-cluster sensitivity, not a serving-population confidence interval. Matching seeds does not enforce matching text; low-load quality differences cannot be credited to live cuts when none occur. The report keeps individual quality losses visible.
- Recorded exposure is now **124 unique dataset indices**: the original 0–99 plus the 24 validation questions. The other 376 are provisionally unused; external/unrecorded use and pretraining remain unknown. The initial exposure audit describes the pre-campaign state and has not been overwritten.

## Jobs, recovery, and compute

**The completed 5B campaign has no active jobs or missing GPU results.** Six successful H100 allocations used **5.144 GPU-hours** including startup/calibration/drain, with no GPU retries. Earlier development work used 1.349 GPU-hours separately.

CPU job 6482012 failed on a missing deployment copy of the unchanged tracked metrics module. After restoring it, CPU-only job **6502005** completed in 56 seconds. Its aggregate and all 18 per-run analysis files match the local analysis exactly. The local observer had independently stopped after connection failures; final collection and assessment were completed during 5C. [Recovery evidence](reserved-validation/analysis/postprocessing.json) preserves the diagnosis and sanitized logs. No model inference was repeated.

Executed source label `fd2fa46` predates the requested history squash into `d3846c4`; per-run source snapshots and hashes preserve the executed code independently. Cluster login and private workspace settings are omitted. Launch/collection helpers accept environment configuration.

## 6B findings and suggested next step

The [6B feasibility report](laser-feasibility/REPORT.md) recommends a **conditional go for small baseline integration and a development-only mechanics gate**, rather than a large 6C campaign. The unchanged LARB controller remains the candidate. No model generation or GPU allocation was used in 6B.

21 CPU tests cover the paper-derived budget/load rules, geometric confidence, invalid probes, exact prefix identity, cancellation, transition/final boundaries and cost accounting. Five installed vLLM files match the official 0.11.2 tag. An offline cached-tokenizer check used synthetic strings only. These are CPU/static checks, not a working serving-baseline claim.

The paper's target load 10 saturates at threshold 0.97 in our two-slot engine and never reduces budgets for load. A capacity-scaled target is an explicit proposed adaptation. ATP/probe/confidence choices inherited from DEER are pinned and labeled; a new confidence implementation avoids sampled-token/dictionary-order assumptions. The public AsyncLLM lacks per-request KV fork/pause/resume, so a public-API serial replay route must pay recomputation and disclose queue/RNG changes. Prefix caching does not by itself solve rollback.

The LASER implementation route is preserved as an option rather than the immediate roadmap. The current priority is the missing fixed-budget serving controls, then cut-level diagnosis. Prior-work overlap is not a veto on practical contribution; a fair claim should follow measured deadline/quality/compute value.

The comparison would test LARB's deadline/quality/compute tradeoff against load-adaptive confidence control; it would not establish novel downstream-deadline forecasting. The pinned public Dynasor helper findings remain scoped, and ACER's full algorithm remains a literature-access gap. [Prior-work plan](evaluation-plan/PRIOR-WORK.md).

## Focused fixed-budget controls (2026-10-24)

The user authorized staged testing of fixed2048, fixed4096, admission and live. The original controller files remain unchanged; an isolated extension preserves the original admission/live functions and adds pressure-independent fixed choices. [Frozen plan](baseline-controls/PLAN.md), [exact settings](baseline-controls/plan.json), [ledger](baseline-controls/campaign.json), [status snapshot](baseline-controls/status.json).

CPU preflight **6512233 passed** on PACE: source/dependency checks, 26 CPU tests, and reproducing one saved real-result grade. The submitted serial GPU chain is **6512258 gate → 6512259 late burst → 6512260 sustained pressure**. CPU finalizer **6512261** runs after all three terminate, including cancellation/failure, and produces an explicit complete or partial report. Continuation depends on mechanical validity, never favorable correctness. No automatic retries or additional repair allocations are enabled.

Comparison cohort: **83, 12, 89, 98, 28, 42, 94, 76, 10, 65, 1, 77**, selected by a saved hash over exposed indices 0–99, excluding calibration 0/2. Two reversed-order blocks across two pressure conditions yield **192 measured outcomes on 12 unique questions**. The gate uses known exposed indices 1/4/5 and is excluded. No additional reserved questions are consumed. The original hard allocation ceiling was 10 hours (2+4+4), with one H100 at a time; final actual use is recorded below.

The source label is the SHA-256 of `baseline-controls/source-lock.json`, rather than an invented executed Git commit. Per-run source/input snapshots preserve exact provenance. Operator-only status/collection/monitor helpers and the mutable campaign ledger sit outside that scientific source lock. Cluster login and private paths remain local configuration.

The campaign is now **complete and graded**. Gate 6512258, late-burst 6512259, sustained-pressure 6512260 and CPU finalizer 6512261 all completed with exit 0. There are 192/192 measured outcomes, 222 raw requests including gate/calibration, no cap failures, no missing results and no active jobs. Actual GPU cost was **1.738 hours**, with no retries. The finalizer took 31 seconds. [Final report](baseline-controls/REPORT.md), [aggregate](baseline-controls/analysis/summary.json), [independent local verification and paired diagnostics](baseline-controls/analysis/assessment.json). All comparison grades match cluster output byte for byte, mechanical checks pass, and archive hashes match. The startup snapshot is retained as historical evidence.

Late-burst correct-on-time counts (out of 24) are fixed-2,048 **9**, fixed-4,096 **5**, admission **3**, live **9**; eventual correctness is **22/22/23/22**. Sustained counts are **23/8/9/21** on time and **23/22/23/22** eventual. Live beats admission and fixed-4,096, but fixed-2,048 ties it in burst and outperforms it in sustained pressure with fewer tokens and lower latency. These are 12 repeated exposed questions, not a population claim or an extension of held-out 5C evidence. All eventual errors concentrate on question 94.

The [offline diagnosis](baseline-controls/diagnosis/REPORT.md) is now complete. Question 1's sustained loss is mostly service time: live waits 36.84 s, thinks 5,602 tokens with one waiter and no cut, and finishes at 127.33 s; fixed-short waits 34.99 s and finishes correctly at 77.09 s. Question 94's key quality loss has equal 2,048 cutoffs but output divergence at token 124 before the live decision; it is not evidence of a causal cut error. Three sustained cuts arrive after 2,048 (1,399 tokens already spent beyond short), five are nonbinding natural closures, and no paired extra-thinking case improves correctness. Live's sampled sustained queue area is 23.2% above fixed-short.

The smallest proposed change is a one-waiter threshold at both admission and live update, preserving budgets, cue/cap and scheduling. It has **not been implemented**. The proposed 24-question, hash-selected development test retains fixed-2,048, fixed-4,096 and unchanged live, and contrasts isolated quality, sustained pressure and frozen slack/burst/recovery arrivals. It would contain 576 measured outcomes with two predefined blocks/seeds. Cohort, exact manifest, ordering and compute cap still need freezing before an authorized run; no new GPU jobs were submitted. The question is whether extra reasoning has a reproducible benefit on an outcome-independent cohort that offsets congestion cost; if not, fixed-short remains the practical choice.

## Evidence-led literature audit

The [new audit](literature-audit/REPORT.md) reviews five full papers and their figures/setup, rechecks ACER's restricted access, and independently aggregates pinned P-PAS+ public logs. It treats conceptual overlap as context, not a reason to narrow or abandon LARB. A useful mechanism, substantial empirical improvement, sound runtime/cost evidence and generalizable failure characterization are all possible contributions.

Key findings: LASER's budget-only ablation drives most latency reduction; combined confidence recovers some quality but its simulation/load semantics and ablation latency scale need clarification. Dynasor has substantial integrated evidence, with gains from allocation and scheduling varying by workload; its online headline is not a single-chain CoT result. P-PAS+ public logs reproduce 3.022%/3.053% mean-latency gains against best tested static budgets, including matched request counts; its Qwen log has ten seeds where the appendix describes eleven. UniBoost's displayed 35.1% P99 gain coexists with a 19.1% mean-latency regression in one comparison. Queueing-aware allocation's optimum is conditional on fitted curves, stationary task mixture and utility. ACER's algorithm/figures remain unassessed; do not infer either weakness or exclusion from its abstract.

The next local study can test the one-waiter mechanism while measuring whether longer reasoning buys useful quality on an outcome-independent cohort. Keep the research space open: use our evidence to choose further mechanisms, and add prior-method comparisons when their scientific question and runtime semantics are clear. The audit is read-only research and CPU arithmetic verification; no controller edits, model inference or GPU submissions occurred. [Sources](literature-audit/sources.json), [reproduced arithmetic](literature-audit/verification.json), [reproduction notes](literature-audit/README.md).

## Reproducing or sharing the work

The [execution README](reserved-validation/README.md) gives audit, grading, aggregation, and assessment commands. The report explains findings; result folders retain raw inputs, clocks, events, executed sources, grades, hardware, and accounting. Eight runner/audit tests and the exact frozen-source/input preflight pass. All six lossless scheduler archives were checked against both compressed and raw hashes. The grading metrics dependency is explicitly recorded in the 5C diagnostics.

A short update here can help the next person: what changed and why, what passed, links to results/configuration, any active jobs or unresolved issues, compute used, and one next action. Detailed history fits better beside the run evidence. Repository-relative paths and local environment configuration keep the notes portable.
