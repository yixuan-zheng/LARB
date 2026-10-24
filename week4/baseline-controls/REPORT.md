# Fixed-budget comparison: final assessment

The campaign finished successfully. Live LARB improves deadline success over admission-only and fixed-4,096, but does **not** outperform fixed-2,048 on these pressure traces. Fixed-2,048 ties live on late-burst correct-on-time and eventual correctness, while using fewer tokens; under sustained pressure it delivers more correct-on-time answers, higher eventual correctness, and lower latency and token use.

## Completion and verification

| Stage | Job | Status / exit | Allocation elapsed |
| --- | --- | --- | --- |
| CPU preflight | 6512233 | Completed | Source/runtime/scorer and 26 checks passed |
| GPU mechanics gate | 6512258 | Completed / 0:0 | 21m 29s |
| GPU late burst | 6512259 | Completed / 0:0 | 40m 24s |
| GPU sustained pressure | 6512260 | Completed / 0:0 | 42m 23s |
| CPU finalizer | 6512261 | Completed / 0:0 | 31s |

No stages remain active and no ETA is needed. All **192/192 measured outcomes** are present: 24 per policy per condition. The gate adds 24 excluded outcomes; six calibration requests bring the raw total to **222**. There are no missing terminal receipts, cap failures, or grader parse issues in the comparisons. Wrong answers and late answers are retained. GPU allocations total **6,256 seconds (1.738 GPU-hours)** including gate, startup, calibration, inference and drain; the comparisons alone used 1.380 GPU-hours. No GPU retries were needed.

The [CPU finalizer aggregate](analysis/summary.json), [scheduler status snapshot](status.json), [ledger](campaign.json), and per-run accounting agree. [Local verification](analysis/assessment.json) reruns mechanical validation and pinned grading against saved raw outputs: all six comparison analysis files match the cluster-produced files byte for byte, both lossless scheduler archives match their compressed and decompressed hashes, and per-run summaries equal the finalizer aggregate. Original cluster analysis bytes are preserved. The earlier [gate checks](gate-checks.json) remain separate.

## Results

Each row has **24 outcomes from the same 12 development questions repeated in two blocks**. Eventual accuracy includes correct answers that missed the deadline. Latency is client completion time from scheduled arrival, including queueing, across all outcomes. P95 follows the existing metrics implementation. Output tokens count all generated tokens, including forced cues and terminal tokens; thinking tokens are also shown separately. These token counts describe inference work, not measured energy or monetary cost.

| Traffic | Policy | Correct on time | Eventual accuracy | Median / p95 latency (s) | Thinking tokens | Total output tokens |
| --- | --- | --- | --- | --- | --- | --- |
| late burst | fixed2048 | 9/24 (37.5%) | 22/24 (91.7%) | 118.77 / 199.36 | 41,512 | 53,793 |
| late burst | fixed4096 | 5/24 (20.8%) | 22/24 (91.7%) | 170.57 / 274.55 | 63,244 | 74,169 |
| late burst | admission | 3/24 (12.5%) | 23/24 (95.8%) | 170.62 / 281.73 | 58,217 | 69,957 |
| late burst | live | 9/24 (37.5%) | 22/24 (91.7%) | 119.68 / 201.10 | 45,947 | 58,388 |
| sustained pressure | fixed2048 | 23/24 (95.8%) | 23/24 (95.8%) | 50.81 / 77.09 | 42,359 | 53,815 |
| sustained pressure | fixed4096 | 8/24 (33.3%) | 22/24 (91.7%) | 111.18 / 175.13 | 66,764 | 77,992 |
| sustained pressure | admission | 9/24 (37.5%) | 23/24 (95.8%) | 107.71 / 182.84 | 62,415 | 74,069 |
| sustained pressure | live | 21/24 (87.5%) | 22/24 (91.7%) | 59.35 / 84.41 | 46,155 | 57,537 |

Late-burst deadline is **96.89 s** per request; sustained-pressure deadline is **95.03 s**. They come from each job's frozen calibration and remain identical across policies within that job. Goodput horizons across two blocks are 208.24 s and 503.67 s respectively, so counts are compared within condition rather than pooling differently calibrated goodput rates. See each saved `trace.json` for arrivals, calibration and block order.

## What the comparison tells us

**Late burst:** live improves correct-on-time from admission's 3/24 to 9/24 (+25.0 percentage points), reducing median latency by 29.9% and output tokens by 16.5%, but loses one eventual correct answer (23 to 22). Relative to fixed-4,096, live gains four on-time answers with equal eventual correctness, 29.8% lower median latency and 21.3% fewer output tokens. Fixed-2,048 matches live's exact on-time and accuracy indicators in both blocks, with slightly lower median latency (118.77 vs 119.68 s) and 7.9% fewer output tokens relative to live. Both still miss many burst deadlines: shortening everyone does not remove the queue-capacity limit.

**Sustained pressure:** live improves correct-on-time from admission's 9/24 to 21/24 (+50.0 points), with 44.9% lower median latency and 22.3% fewer output tokens, while eventual correctness falls from 23 to 22. It also beats fixed-4,096 by 13 on-time answers with equal eventual correctness, 46.6% lower median latency and 26.2% fewer output tokens. However, fixed-2,048 gets 23/24 on time and eventual correct, compared with live's 21/24 on time and 22/24 eventual. Fixed-2,048 has 14.4% lower median latency and 6.5% fewer output tokens relative to live. Live's extra thinking does not buy an accuracy advantage here.

The block-level view matters. Late-burst on-time counts for fixed-2,048/live are 5/5 in block 0 and 4/4 in block 1. Sustained counts are 12/10 and 11/11. Live's two sustained losses versus fixed-2,048 are question 1 (a deadline loss with eventual correctness retained) and question 94 (an eventual correctness loss), both in block 0. All eventual errors across the two comparisons occur on question 94; this is a concentrated failure, not evidence of a broad quality distribution. Live loses eventual correctness versus admission on question 94 in block 1 of each condition. The [paired assessment](analysis/assessment.json) lists all gains and losses without discarding unfavorable cases.

Live made four reductions, all binding, in late burst; sustained pressure had 15 reductions, ten binding. Five sustained reductions therefore did not reach a forced live cutoff before natural thinking ended. This is a useful starting point for cut diagnosis, not evidence that every nonbinding update wastes substantial compute. Admission/live initial budgets match 24/24 in the burst but only 12/24 under sustained pressure: earlier completions change later queue states. That feedback is part of the end-to-end policy comparison, and prevents interpreting every paired outcome as the isolated causal effect of a single cut.

## Research implications and a useful next step

The live-versus-admission result is real within this experiment, but aggressive fixed shortening explains as much or more of the pressure benefit on this cohort. The current evidence supports adapting long-budget admission decisions when pressure appears; it does not establish that the present adaptive policy beats a simple short static budget. Fixed-4,096 provides neither an accuracy gain nor a favorable latency tradeoff here. Similar prior methods do not block a contribution; practical value still needs to be demonstrated against the strongest simple alternative.

A natural next step is an **offline diagnosis using these saved records**, leaving the controller frozen:

1. Trace question 1's sustained deadline miss and question 94's quality differences, including queue delay, when cuts arrived, thinking already spent, cue/answer time and raw reasoning. Separate changed scheduling/sampling trajectories from claims that a particular cut caused an error.
2. Categorize live decisions: binding versus nonbinding cuts, late cuts after substantial thinking, cuts that cannot plausibly save a deadline, and requests allowed extra thinking without an observed quality return. Compare downstream queue relief with fixed-2,048's simpler behavior. Offline replay can reveal candidates; unobserved answers and service times remain counterfactual.
3. Use that diagnosis to decide whether a small deadline/cue-and-answer reserve rule, better cut selection, or a simpler pressure-triggered short budget has a defensible mechanism. Preserve the current controller as the reference; any proposed revision needs its own frozen development test and subsequent untouched evaluation.
4. Before claiming adaptation's application value, plan a matched evaluation including **low load or mixed demand and questions where longer reasoning may help**. Fixed-2,048 must remain a comparator. Predefine cohort selection and quality/deadline criteria rather than searching for examples that favor LARB. A later held-out comparison can test whether adaptation preserves quality when slack exists and recovers short-budget efficiency under pressure.

No new experiments or controller changes were made for this assessment. LASER integration can remain an optional later comparison; it need not delay understanding the simpler baseline gap.

## Scope and reproduction

This is a small exposed development comparison: 12 unique questions, two order-reversed blocks, two pressure traces, one allocation per condition, one engine/model configuration. The repetitions are not independent population trials. There is no low-load static comparison here, no demonstrated static-budget accuracy penalty, and no claim of population accuracy or broad dominance. Keep the earlier 24-question held-out 5C results separate; they tested live versus admission, not these fixed controls. No new unique questions were exposed by this campaign.

See [PLAN.md](PLAN.md), [plan.json](plan.json), and per-run source/input/runtime snapshots for the frozen design. To repeat the CPU-only verification from the repository root, use a Python environment with the recorded grading versions (including Math-Verify 0.9.0) and run:

```bash
python -B week4/baseline-controls/assess.py
```

The script preserves cluster analysis bytes, audits records and hashes, reproduces grading, and writes `analysis/assessment.json`. It performs no inference or submission. [The execution README](README.md) covers navigation and the original preflight checks. The startup snapshot is historical; the completed ledger and report describe the final state.

The subsequent [offline diagnosis](diagnosis/REPORT.md) completes the saved-trace investigation and proposes a one-waiter threshold ablation and outcome-independent workload design. The controller remains unchanged; the experiment is a proposal only.
