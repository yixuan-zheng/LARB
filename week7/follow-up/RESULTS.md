# After Experiment 3

Experiment 3 left a practical distinction for LARB. A policy can allocate more compute to the right questions while doing little to distinguish two reasoning paths for the same question.

| Checkpoint | Essential result | Decision |
| --- | --- | --- |
| [Experiment 3 held-out validation](../hidden-state-probes/independent-validation/FINAL-REPORT.md) | At 164 extensions, the hidden-state probe gained **7.375 expected correct answers (+2.24 pp)** over prompt-only, 95% interval **−0.15 to +4.98 pp**. Within-question concordance was **46.1%**. An exploratory decomposition attributed **88%** of the lift to shifting extensions between questions. | Inconclusive at the frozen **+3.45 pp** threshold. |
| [Nonlinear readout](mlp-decomposition.json) | The MLP gained **5.00 and 5.75** expected answers over the matched linear probe. The between-question contributions were **3.75 and 4.125** (75% and 72%). Within-question ranking went **36.9% → 46.2%** and **50.0% → 48.4%** across the two splits. | Exploratory aggregate gain. Within-question contributions had intervals crossing zero in both splits. |
| [Temporal checkpoint features](temporal-results.json) | Two hidden-state distances from 2K to 4K changed within-question concordance by **+1.54 and −4.69 pp**, and yield by **+0.75 and −3.00** answers. | Failed the predeclared advance rule. Training-size, direct-target, and last-token checks also gave no consistent trajectory-ranking improvement. |
| [Repair evidence screen](REPAIR-SCREEN.md) | The revised single-reviewer screen ordered **one of 24** sibling pairs. Twenty of 48 attempts failed the verbatim-evidence check. The sole ordered pair went against the prediction in both outcome halves. | Coverage failure. The relationship between identifiable repairs and continuation benefit remains unresolved. |
| [Serving replay](serving-replay.json) | The CPU replay matched peak queue depth in **11/12 phases** and deadline status for **119/120 requests**. It reproduced 32 correct-on-time completions versus 31 logged using archived output lengths. | Timing baseline check. No matched question-value versus uniform-value comparison has been measured. |

The probe follow-ups reuse previously examined questions. The grading halves are disjoint within each checkpoint and reuse the same question groups. These results support keeping question-level serving work separate from the open trajectory research question.

Run `python3 -B week7/follow-up/verify_decomposition.py` from the repository root to verify the MLP decomposition from archived checkpoint scores, weights and observed benefits. The temporal and serving JSON files are result summaries. Raw traces and private reviewer records remain in their original archives.
