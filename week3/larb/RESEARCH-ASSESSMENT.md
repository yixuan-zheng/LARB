# Research assessment — 2026-10-17

Engineering feasibility is established. Usefulness is promising on one development burst. Research novelty remains unproven.

The 100-problem sequential comparison found no shorter mode within the preliminary three-point accuracy tolerance: full thinking scored 95%, and the 2,048-token budget scored 90%. The concurrent burst pilot delivered 6/12 correct on-time answers with live updates, versus 4/12 full and 3/12 arrival-only. Full and live both eventually completed 11/12 correctly, but exchanged a failure. Only one live cutoff bound after generation had begun.

The next question is whether changing an ongoing reasoning budget adds useful completions beyond selecting the budget at execution admission. Compare full thinking, arrival-time budgeting, admission-time budgeting, and admission plus live updates on matched traces. Include bursts after initial requests begin generating, freeze settings, and vary policy order. Do not launch a larger campaign before this distinction is resolved.

## Prior work and novelty boundary

- [s1](https://arxiv.org/abs/2501.19393) establishes budget forcing. Forcing thinking to end is not the contribution.
- [Dynasor/Certaindex](https://arxiv.org/abs/2412.20993) integrates dynamic reasoning compute allocation with serving and scheduling.
- [LASER](https://arxiv.org/html/2606.31580v1), June 2026, combines initial budgets with load-responsive early-exit thresholds updated during reasoning. Its reported serving evaluation uses discrete-event simulation with a single-server FIFO queue.

Real continuous-batching evidence may support a narrower systems contribution, but a different engine or hardware alone does not establish novelty. This is a targeted literature check, not an exhaustive review. A stronger study should distinguish the policy from closely related methods and assess correct-by-deadline completions alongside eventual accuracy and final-answer costs.

Recommendation: continue one bounded admission-versus-live comparison. If admission captures the benefit, drop the claim that mid-request intervention is the key contribution. If live updates consistently help at an acceptable quality cost, expand evaluation on held-out problems and multiple traces. The current work already supports a credible course project, but not a demonstrated novel-paper claim.
