# Experiment 3 · Independent hidden-state validation

**Decision: inconclusive.** At the same 164-extension budget, the frozen 4K hidden-state predictor yielded **166.875 expected correct answers versus 159.500 for prompt-only** across 329 eligible checkpoints. The lift was **+7.375 answers (+2.24 percentage points)**. The paired, question-clustered 95% interval was **−0.15 to +4.98 points**, equivalent to **−0.50 to +16.39 expected answers** on this cohort. The frozen positive criterion required an observed lift of at least 3.45 points and a lower bound above zero. The interval still includes gains above 3.45 points.

## Allocation results

| Policy | Extensions | Expected correct | Beneficial selected | Harmful selected | Beneficial missed | Expected suffix tokens | Expected suffix call hours |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| All short | 0 | 134.000 | 0 | 0 | 127 | 474,343 | 2.03 |
| Prompt-only | 164 | 159.500 | 64 | 6 | 63 | 1,050,963 | 4.48 |
| 4K hidden state | 164 | 166.875 | 72 | 4 | 55 | 1,048,927 | 4.47 |
| All long | 329 | 189.375 | 127 | 8 | 0 | 1,607,292 | 6.83 |

Expected correctness uses the empirical mean of eight draws per policy per checkpoint. A beneficial or harmful extension has a positive or negative empirical long-minus-short contrast, respectively. At eight draws per arm, an individual checkpoint's estimated contrast is noisy. The paired interval uses 10,000 question-clustered resamples, keeps both reasoning seeds together, and recomputes the allocations within each resample. Policy token and time estimates use the measured suffixes, including their prefill time. They exclude probe computation and serving overhead.

## What the result supports

The hidden-state policy selected eight more empirically beneficial checkpoints and two fewer harmful checkpoints at nearly identical measured suffix cost. Among 158 questions with two eligible seeds, 76 had different empirical continuation benefits. On those pairs the hidden-state score had **46.1% concordance**, counting ties as half, versus **50%** for prompt-only, which ties the two seeds. The aggregate lift therefore has no corroboration from this within-question ranking check. The result does not meet the frozen criterion for moving this predictor into a serving evaluation.

## Coverage and compute

All 360 planned prefix attempts were accounted for. The 329 eligible checkpoints yielded **5,264 verified suffix draws**, including 12 gate draws and 5,252 production draws. The controller's live merge and independent local reconstruction agreed on every scheduled identity and file hash. The complete cohort's forecast seal was verified before the isolated evaluator opened the pinned answer source.

Collection produced **16.65M suffix tokens** and processed **22.18M input tokens** in **70.86 aggregate call-hours**. Slurm reported **79.46 elapsed L40S allocation-hours**, including prefix collection, the recovered failure, and engineering and replay gates. The central ledger closed at **94.5 requested L40S-hours** against the 105-hour ceiling. Aggregate allocation time excludes queue waits.
