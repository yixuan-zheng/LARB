# Week 8

This week's plan is in [PLAN.md](PLAN.md). It refocuses the prediction effort on question-level allocation, qualifies the serving workload, and tests that allocation in the existing replay. The end-of-week decision record and integrated report will be linked here when complete.

## Serving qualification (stopped at the preview)

The serving thread is set up in [scaled-serving/README.md](scaled-serving/README.md):

- [reports/P2A-STATUS.md](scaled-serving/reports/P2A-STATUS.md): the GPU verdict — the Omni-MATH preview stopped the line — and the next action.
- [reports/SLOPE-ANALYSIS.md](scaled-serving/reports/SLOPE-ANALYSIS.md): why the 4k→8k budget slope stopped appearing, and the AIME 2025+2026 candidate pool selected from that analysis.
- [reports/P2A-DECISION.md](scaled-serving/reports/P2A-DECISION.md): the qualification decision record.
- [reports/POOL-DECISION.md](scaled-serving/reports/POOL-DECISION.md): the 2023 AIME subset is a valid slope witness (+29.2 points from 4k to 8k on 24 items) but too small for a 5-6 point main comparison; the pre-declared Omni-MATH fallback failed its preview (-4.2 points, 29.2% at 8k).
- [reports/P1-SCREEN-AUDIT.md](scaled-serving/reports/P1-SCREEN-AUDIT.md): per-pool P1 records, the `\dfrac` grading false negatives and the lossy Math-Verify false positive.
- [reports/P2A-QUALIFICATION-PLAN.md](scaled-serving/reports/P2A-QUALIFICATION-PLAN.md): the GPU job order, transition risks, how the run was executed and the pass/fail records.
- [reports/PRECALIBRATION-240.md](scaled-serving/reports/PRECALIBRATION-240.md): the 750-1200/h calibration grid and its caveats.

The serving go/no-go is decided: **P2 is not authorised.** The Omni-MATH
preview showed no 4k→8k budget slope, and the frozen stop rule closed the
calibration and live phases before they ran (`scaled-serving/results/p2a/STOP.md`,
local). A different pool needs its own pre-declaration and preview.
