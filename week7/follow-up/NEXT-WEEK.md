# Possible directions for next week

## Qualify the scaled-serving workload

Build on the merged [scaled-serving GPU gates](../scaled-serving/reports/P1-REPORT.md). The runtime mechanics worked, but the proposed preview lacked 4K-to-8K quality headroom and the measured 180-second deadline regime moved abruptly from little pressure to overload. Recover the P1 request and scheduler logs, verify the candidate 2023 AIME overlap against exact prompts and grading contracts, and check headroom on the actual intersection. If it is unsuitable, predeclare one alternative pool and measure a fresh preview before considering P2. Use a measured deadline-pressure band. The existing report identifies 240 seconds as a candidate to calibrate.

## Isolate the value of question-aware allocation

Reuse the [Week 5 Explorer timing and targeting work](https://github.com/yixuan-zheng/LARB/blob/7c16237475e2adba8c8b32090b2148990874108d/week5/explorer/PATH-MEMO.md) and [Week 6 audit](../../week6/README.md) when checking deadline and queue behavior. Hold the admission rule, arrivals, deadline and runtime model fixed. Compare a frozen question-only continuation value with constant value in the same scheduler. The outcome is correct-on-time answers per minute. Fixed 4K, fixed 8K and arrival-only give context. Advance to a live test only if the paired replay advantage survives plausible timing changes and the workload has measured quality headroom. This complements workload qualification and can progress independently of trajectory prediction.

## Keep recovery evidence as a bounded research question

The repair screen exposed a grounding and coverage problem. Before another predictor or GPU run, propose a way to anchor judgments to verifiable reasoning spans or executable subgoals and test evidence fidelity on a small blinded sample. Advance only if enough sibling pairs can be ordered reproducibly to test marginal benefit. Fresh math questions would be the first generalization check, with executable coding subgoals a later option. Keep this separate from serving milestones.
