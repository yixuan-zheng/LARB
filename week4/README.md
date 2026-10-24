# Week 4: Load-Adaptive Reasoning Budgets

This week asks whether updating a running request's thinking budget helps more answers finish correctly on time than choosing the budget once, at admission.

The completed development implementation and results are in [step1/](step1/README.md). The GPU gate passed **176 checks**. In the controlled development comparison, live updates produced **12/24 correct-on-time answers**, compared with **8/24 for admission-only**. These are two replays of the same 12 exposed questions; the [report](step1/controlled-comparison/REPORT.md) explains what we can and cannot conclude.

## Week closed; picking up next week

The [actual checkpoints](CHECKPOINTS.md) now reflect the route we followed, including the extra fixed-budget testing, diagnosis and deeper literature audit. [Next-week options](NEXT-WEEK.md) compares possible directions, their risks and our recommendation. All campaign results are collected; no jobs are active.

The [handoff](HANDOFF.md) summarizes what is finished, what was checked, and a suggested next step. The [5B campaign and 5C assessment](reserved-validation/REPORT.md) are complete: +12.50 percentage points correct on time across pressure workloads, with equal overall eventual correctness. The effect is strongest under sustained pressure; see the report for quality tradeoffs and uncertainty. [The new 5A/6A planning notes](evaluation-plan/README.md) cover the exposure audit, frozen validation design, closest-method review, and feasibility of deadline-aware coordination.

The [fixed-budget comparison](baseline-controls/REPORT.md) is complete: live beats admission and fixed-4,096, but fixed-2,048 ties live on burst deadline success and wins under sustained pressure with fewer tokens. All 192 measured outcomes are verified; GPU use was 1.738 hours. The [offline diagnosis](baseline-controls/diagnosis/REPORT.md) identifies the two-waiter blind spot and proposes a one-waiter ablation with fixed-short retained as a baseline. It also explains a fair slack/burst workload test; no controller change or new GPU run has begun. LASER integration remains deferred.

The [6B CPU/interface investigation](laser-feasibility/REPORT.md) is also complete. It identifies a feasible adaptation route and the runtime/fairness gates that remain before a new GPU comparison. No 6C campaign has started.

The [evidence-led literature audit](literature-audit/REPORT.md) examines actual mechanisms, figures, costs and comparison limits across the closest reasoning and scheduling studies. It informs our own research choices without treating similar ideas as disqualification.

Useful starting points:

- [6B LASER feasibility and CPU checks](laser-feasibility/README.md)
- [5B execution and reproduction](reserved-validation/README.md)
- [5C result and research decision](reserved-validation/REPORT.md)
- [5A evaluation and 6A research plans](evaluation-plan/README.md)
- [Step 1 overview and reproduction commands](step1/README.md)
- [Controlled comparison report](step1/controlled-comparison/REPORT.md)
- [Admission boundary and GPU validation](step1/admission-control/README.md)
- [Research checkpoints](CHECKPOINTS.md) and [comparison guidance](WORKING-RULES.md)

## Leaving notes for the next person

A short update to [HANDOFF.md](HANDOFF.md) helps the next person continue: what changed, what passed, where the results live, any open questions or active jobs, compute used, and a useful next action.

READMEs work well for navigation and runnable commands; reports explain findings and limitations. Each experiment's plan and configuration capture the intended comparison, while its result folder holds inputs, raw outcomes, scores, checks, and environment details. Keeping failed attempts alongside successful ones helps explain decisions without reconstructing a chat history.

[Step 1's notes](step1/README.md#sharing-progress) give a little more detail. Repository-relative paths and configurable local environments make these notes easier for someone else to use.

Earlier code and evidence remain in [week3/larb](../week3/larb/README.md). Week 4 reuses that code where possible.
