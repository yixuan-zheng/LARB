# Week 4: Load-Adaptive Reasoning Budgets

This week asks whether updating a running request's thinking budget helps more answers finish correctly on time than choosing the budget once, at admission.

The implementation and results are in [step1/](step1/README.md). The GPU gate passed **176 checks**. In the controlled development comparison, live updates produced **12/24 correct-on-time answers**, compared with **8/24 for admission-only**. These are two replays of the same 12 exposed questions; the [report](step1/controlled-comparison/REPORT.md) explains what we can and cannot conclude.

## Picking up the work

The [handoff](HANDOFF.md) summarizes what is finished, what was checked, and a suggested next step. No jobs are active. The next research question is whether the benefit holds on reserved questions and other traffic patterns, after checking which questions have already been exposed.

Useful starting points:

- [Step 1 overview and reproduction commands](step1/README.md)
- [Controlled comparison report](step1/controlled-comparison/REPORT.md)
- [Admission boundary and GPU validation](step1/admission-control/README.md)
- [Research checkpoints](CHECKPOINTS.md) and [comparison guidance](WORKING-RULES.md)

## Leaving notes for the next person

A short update to [HANDOFF.md](HANDOFF.md) helps the next person continue: what changed, what passed, where the results live, any open questions or active jobs, compute used, and a useful next action.

READMEs work well for navigation and runnable commands; reports explain findings and limitations. Each experiment's plan and configuration capture the intended comparison, while its result folder holds inputs, raw outcomes, scores, checks, and environment details. Keeping failed attempts alongside successful ones helps explain decisions without reconstructing a chat history.

[Step 1's notes](step1/README.md#sharing-progress) give a little more detail. Repository-relative paths and configurable local environments make these notes easier for someone else to use.

Earlier code and evidence remain in [week3/larb](../week3/larb/README.md). Week 4 reuses that code where possible.
