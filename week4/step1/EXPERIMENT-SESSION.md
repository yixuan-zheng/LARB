# Renewed GPU session — October 21

The user explicitly authorized realistic startup/inference budgets, minor
infrastructure repairs, and continuation into the controlled comparison once
checkpoint 1C passes. This supersedes the earlier self-imposed tiny allocation
and two-attempt stopping point. Earlier failures remain preserved.

## Saved limits and sequence

1. Renewed 1C: one H100, <=45min allocation, <=40min driver, <=20min startup,
   <=20min per phase. Same six development questions and four modes; 24 requests.
2. If the real concurrent audit passes, immediately run the controlled comparison:
   one H100, <=90min allocation, <=85min driver, <=25min startup, <=15min per phase.
   Two full-thinking calibration requests, then two reverse-order matched blocks
   of 12 development questions across four policies (96 measured requests).
3. Reserve one diagnosed infrastructure repair if needed. Cumulative new GPU
   allocation ceiling for this session is 3 GPU-hours; no blind retry loop.
   No policy tuning after comparison outcomes. Preserve failed/partial runs.

The comparison plan, source/input hashes, traffic-generation rule, deadlines,
policy orders, grading rules, and continuation criteria are saved before its
measured requests. All policies within the comparison share one engine,
allocation, hardware model/count, settings, instrumentation, and frozen trace.
Client scheduled-arrival to terminal receipt is primary. Caps/errors count as
failures; late requests drain. Repeated questions do not create independent
accuracy examples. This is a diagnostic development comparison, not validation
on reserved questions or proof of a three-point accuracy guarantee.

Do not stop after 1C if it passes. Collect the controlled comparison and produce
the first result table, including a negative or inconclusive result.

## Completed record

Gate job 6440402 passed all 176 checks after 18:13. Comparison job 6440653
completed all 96 measured plus two calibration requests after 58:24. The full
audit and grading passed; live yielded 12/24 correct-on-time versus admission
8/24, with the same +2 difference in each block. See `controlled-comparison/REPORT.md`.
Total renewed allocation was 1:16:37 (1.277 GPU-hours), within the saved ceiling.
No extra infrastructure repair, policy tuning, or inference retry was needed.
