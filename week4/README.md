# Week 4: Load-Adaptive Reasoning Budgets

Does changing a running request's thinking budget help more answers finish correctly on time than choosing its budget at admission?

All implementation and experimental artifacts for this work are in **[step1/](step1/README.md)**. Start with the **[current handoff](HANDOFF.md)**, then read the [working rules](WORKING-RULES.md) and [checkpoints](CHECKPOINTS.md).

Step 1 passed 176 real GPU checks. The controlled development comparison completed: live achieved **12/24 correct on time**, admission-only **8/24**, over two replays of 12 unique exposed questions. See the [report](step1/controlled-comparison/REPORT.md) for limitations and evidence. No jobs remain active.

## How to document and hand off work

Use one authoritative location for each kind of information:

- **HANDOFF.md:** current checkpoint, owner/branch, verified checks, active jobs and collection commands, unresolved issues, compute used, and one concrete next action. Update it at session start and before pushing.
- **step1/README.md and component READMEs:** navigation, exact reproducible commands, dependencies, and the documentation contract. Keep current instructions here; avoid chronological activity logs.
- **PLAN.md and spec.json:** freeze the candidate, inputs, traffic, deadlines, policy order, success criteria, analysis, and compute limit before a new experiment.
- **results/job-ID/:** immutable configuration, executed sources and hashes, environment/hardware, schedule, raw responses/events, scores, validation, and accounting. Keep failures visible. For artifacts omitted from Git, retain checksums and an accessible retrieval location.
- **REPORT.md:** conclusions and their limits, linked to machine-readable results and raw cases. Distinguish CPU checks, GPU validation, development results, and reserved evaluation.

Pull before starting. Read and update the handoff; coordinate file boundaries if someone else is active. Before leaving, run the documented checks, update the handoff and reports, and push code plus essential evidence together. Do not commit credentials, environments, model weights, caches, or duplicate intermediate collections. See the [detailed contract and run template](step1/README.md#documentation-contract).

Week 3 code and historical evidence remain in [week3/larb](../week3/larb/README.md); Week 4 imports reusable code rather than copying its directories. There are no permanent assignments.
