# Protected recoverable-step validation

**STOP the tested readout.** At the frozen charged cost ceiling of 443,689 generator-token equivalents, the demonstrated-step policy reached 25/60 correct, versus 26/60 for question-only and 26/60 for the old direct forecast. Its best feasible accuracy also trailed question-only by one with reader cost set to zero. The gate required two additional correct answers and a positive question-grouped uncertainty interval. The paired bootstrap 95% interval was −8.3 to 0.0 percentage points among 9,999 feasible resamples. One resample had no feasible step allocation.

| Policy | Correct at 29 extensions | Charged tokens at 29 extensions | Best correct at common charged ceiling | Charged tokens at that point |
|---|---:|---:|---:|---:|
| Question only | 26 | 443,689 | 26 | 385,916 |
| Old bounded direct forecast | 25 | 471,124 | 26 | 436,819 |
| Demonstrated step | 25 | 499,099 | 25 | 430,034 |

Fixed 4K gave 23 correct and fixed 8K gave 28. Six eligible pairs improved and one regressed. At its selected frontier point the step policy captured two gains and no regressions. Question-only captured three gains and no regressions. These are retrospective comparisons among prespecified ranked allocations, using realized token costs. No serving or deadline claims follow.

## Readout and audit

The reader returned five STEP, eight READY, and 45 INSUFFICIENT classifications across 58 eligible prefixes. Forty-two responses lacked an exact terminal decision and 45 hit the 96-token cap. Under the frozen parser, malformed outputs fall back to INSUFFICIENT. Median local wall time was 2.91 seconds for the step call, in addition to the question-only reader used to order within each tier.

Before joining outcomes, a single qualitative audit reviewed all five STEP claims and five deterministically sampled READY claims using only the supplied question, excerpt, and reader response. No sampled STEP claim carried out a new operation that advanced the requested result. The reader repeated an existing calculation in two cases, performed calculations on the wrong scope in two, and named an unmet requirement without operating on it in one. One sampled READY claim was supported. The audit did not change any allocation. The test measures this exact reader, output format, and budget. It cannot separate format compliance from reasoning ability or establish whether a different implementation could identify recoverable steps.

## Execution and evidence

PACE job 6958397 completed on November 11, 2026 from 10:53:19 a.m. to 1:35:55 p.m. Eastern in 2h 42m 36s on one L40S. All six engineering calls passed and all 60 planned question-seed pairs completed. Identical prefix IDs and hashes were verified for the 58 eligible paired branches. Two early answers were shared by all policies. The measured run used 176 generator calls, 614,130 generated tokens and 491,548 repeated prefill input tokens. The staged source hashes and frozen evaluation hashes matched. Both local reader files were sealed before the audit and outcome join.

See [results](results/readouts/RESULTS.json), [outcome-blind audit](results/readouts/audit-review.json), [engineering gate](results/job-6958397/gate.json), and the [frozen plan](PLAN.md).
