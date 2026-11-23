# Adaptive reasoning and deadline-aware serving

We asked whether Qwen3-4B could choose how much to reason and whether a load-aware scheduler could turn those choices into more correct answers before a deadline. The independent experiments are complete. The reference replay and policy interfaces are ready for integration checks on the scaling deployment.

## What we found

- Fixed-budget and repeated-continuation runs established that extra reasoning can help, with substantial hindsight allocation headroom. The 56% hindsight token savings on 33 Omni-MATH questions uses observed outcomes. Explicit marginal-gain predictors did not consistently improve on cheap controls after overhead.
- Two GRPO screens trained native Low, Medium, and High actions. The step-24 mixed-workload router learned broad source-level preferences, but did not reliably identify which questions within each source benefited from more reasoning. In the 96-question audit, it chose High for four of ten observed High-only successes. Within-source shuffle would capture 4.56 on average.
- On the eight-slot sustained trace, combined improved correct-on-time goodput by **8.8%** over task-only at equal eventual accuracy and **18.9%** fewer output tokens. The strongest shuffle tied its goodput. At eight slots under bursts, shuffle led overall.
- On the final matched 24-request pressured trace, both probabilistic-plus-load seeds matched archived shuffle goodput while using fewer tokens and delivered **25% higher goodput** than combined. Adding load to the probabilistic policy saved **14%** of output tokens across the paired seeds and reduced queue and tail latency, with three fewer eventual correct answers across 48 replayed requests. The seeds share one workload, and the matched controls ran on separate L40S allocations.

| Policy | Admission and serving behavior |
|---|---|
| **Combined** | Uses a cached learned Low/Medium/High action from the step-24 checkpoint, with load-aware admission reductions and live cuts. Cached replay excludes online routing overhead. |
| **Within-source shuffle + load** | Permutes the learned actions inside each evaluation source and runs the same controller. This ablation needs the full roster and source labels. |
| **Probabilistic-only / probabilistic + load** | Assigns Medium with 60% probability and High with 40%, frozen on development data. It draws once per request, reuses that draw on retries, and optionally applies the same controller. It needs neither dataset metadata nor routing inference. |

The original target was at least 5% higher correct-on-time goodput with at most a two-percentage-point eventual accuracy loss. Combined met the point-estimate target versus task-only on the eight-slot sustained trace. That result did not establish an incremental benefit from learned question-specific allocation over shuffle. One answer on the final trace is 4.17 points, so the trace cannot resolve the accuracy tolerance.

## Read, integrate, or reproduce

| Start here | Contents |
|---|---|
| [Final report](FINAL-REPORT.md) · [Research narrative](RESEARCH-NARRATIVE.md) | Main findings, predictor and training history, quantitative limits |
| [Workload analysis](WORKLOAD-NOTE.md) · [Presentation](PRESENTATION.md) | Allocation diagnostic, agent-task hypothesis, presentation figures and regeneration command |
| [Results and schemas](results/closeout/README.md) · [Scored arms](results/closeout/live.csv) · [Paired contrasts](results/closeout/paired.csv) | Compact evidence, jobs, machine-readable tables |
| [Policy contract](integration/POLICIES.md) · [Portable policy logic](integration/policy.py) | Modes, ceilings, retry semantics, fixed and component controls |
| [Scaling handoff](integration/HANDOFF.md) · [Model artifacts](integration/ARTIFACTS.md) · [Reproduction](integration/REPRODUCE.md) | Deployment checks, evaluation priorities, adapter verification, staging and smoke tests |

Use the handoff to qualify the actual scaling runtime before a scored run. Keep the High prefix at the 4,096-token ceiling and reserve the separate final-answer allowance. Use the frozen replay for historical parity. For new traffic, use the portable policy with stable original request IDs and record the assignment mechanism. The [Week 8 package](../../week8/adaptive-reasoning/README.md) retains the original feasibility fixtures.
