# Week 7 | Predicting the value of more reasoning

LARB tests whether evidence available at a 4,096-token checkpoint can identify which Qwen3-4B trajectories benefit from continuing to 8,192 tokens.

| Experiment | Result |
|---|---|
| **Experiment 1 — full-prefix forecasting** | **Waiting for verification.** The original matched Qwen3.8-27B run committed zero forecasts after hitting the completion cap. The revised A100 smoke test, job `6984712`, was pending at the publication check on November 12. The full rerun is pending the smoke result. This is an engineering failure with no prediction result. [Plan](full-prefix-baseline-v2/PLAN.md) · [Diagnosis and correction](full-prefix-baseline-v2/ENGINEERING.md) |
| **Experiment 2 — repeated continuation sampling** | **Complete.** Across 58 checkpoints, eight draws per arm gave 167/464 correct at 4K and 230/464 at 8K. Mean marginal benefit was **+13.6 points** with a question-grouped 95% interval of **+5.8 to +22.4 points**. [Report](continuation-sampling/REPORT.md) |
| **Hidden-state correctness replication** | **Complete.** Direct per-checkpoint extraction covered all 115 trajectories. The 4K four-token mean reached **0.767 AUROC** versus **0.673** for prompt-only. The lift interval included zero. The target was archived 8K correctness. The separate marginal-benefit probe has not been fitted. [Report](hidden-state-probes/direct-reference/REPORT.md) |
| **Bounded-prefix reader** | The 512-token readout reached **22/57 correct** versus **25/57** for the same reader with the question alone, at 28 extensions. [Report](bounded-prefix/REPORT.md) |
| **Recoverable-step reader** | The demonstrated-step readout reached **25/60 correct** versus **26/60** for question-only at the charged ceiling. The audit found output truncation and reasoning errors. [Report](recoverable-step/REPORT.md) · [Audit](recoverable-step/METHODOLOGY-AUDIT.md) |

## Reproduce the completed analyses

Run from the repository root in a disposable checkout. Extract the archived inputs and copy the shared Week 6 helpers into their historical paths first. The archives include the draw and branch records used for grading. Reader packets, forecasts and locks are preserved where needed to replay a comparison. The hidden-state feature matrix is included so scoring requires no GPU.

```sh
tar -xzf week6/research-handoff/evidence.tar.gz
cp -R week6/research-handoff/code/. week6/
cp week7/bounded-prefix/week6-joined-predictions.json week6/question-prefix-comparison/joined-predictions.json
tar -xzf week7/recoverable-step/results/evidence.tar.gz
tar -xzf week7/continuation-sampling/results/evidence.tar.gz
```

- **Bounded prefix.** Run `python3 -B week7/bounded-prefix/score.py` in the disposable checkout. It rewrites its result file.
- **Recoverable step.** Copy `week7/recoverable-step/results/readouts` to a scratch directory and remove the copied `RESULTS.json`. Run `python3 -B week7/recoverable-step/score.py week7/recoverable-step/results/job-6958397 <scratch-readouts>`.
- **Experiment 2.** Unpack `continuation-sampling/full-release.tar.gz` into a scratch directory. Run its `test_study.py`, then `score.py week7/continuation-sampling/results/run week7/recoverable-step/results/job-6958397/questions.json <new-summary.json>`.
- **Hidden states.** With NumPy and scikit-learn 1.7.2, run `python3 -B week7/hidden-state-probes/direct-reference/score.py week7/hidden-state-probes/direct-reference/results/job-6998719 <new-results.json>`. Extraction uses the [pinned upstream helper](hidden-state-probes/DESIGN.md) and the [direct-reference protocol](hidden-state-probes/direct-reference/PROTOCOL.md).
