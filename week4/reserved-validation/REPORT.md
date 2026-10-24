# 5C: reserved validation assessment

The unchanged live controller passes the frozen continuation screen. Its benefit is **load-dependent and strongest under sustained pressure**, with a smaller late-burst gain and no low-load deadline gain. This supports proceeding to the bounded prior-method investigation in Task 6; it does not establish novelty or a general accuracy guarantee. No controller changes or additional inference were made during 5C.

## Complete result

All six matched H100 jobs completed with successful mechanical audits: **288 measured outcomes on 24 unique questions**, plus 12 excluded exposed-only calibration requests. Each condition/policy has 48 outcomes: 24 questions replayed in two reverse-order blocks. The [frozen plan](../evaluation-plan/EVALUATION.md), [aggregate](analysis/summary.json), and [diagnostics](analysis/assessment.json) contain the definitions and reproducible counts.

| Condition | Admission correct on time | Live correct on time | Difference | Eventual correct: admission / live | Binding live cutoffs |
| --- | --- | --- | --- | --- | --- |
| Low load | 42/48 | 42/48 | 0.00 pp | 47/48 / 48/48 | 0 |
| Late burst | 16/48 | 18/48 | +4.17 pp | 47/48 / 47/48 | 4 |
| Sustained pressure | 23/48 | 33/48 | +20.83 pp | 48/48 / 47/48 | 16 |

The primary equal-weight pressure contrast is **+12.50 percentage points**: live achieves 51/96 correct on time versus admission's 39/96. Overall eventual correctness ties at **142/144 (98.61%)** for each policy. Equal totals conceal tradeoffs: sustained pressure loses one eventual correct answer, while low load gains one. Pressure-only eventual correctness is 94/96 for live versus 95/96 for admission.

| Condition | Paired deadline gains / losses | Paired eventual gains / losses |
| --- | --- | --- |
| Low load | 0 / 0 | 1 / 0 |
| Late burst | 3 / 1 | 1 / 1 |
| Sustained pressure | 12 / 2 | 0 / 1 |

All predefined checks pass: positive pooled pressure benefit; neither pressure condition negative; overall eventual difference within the observed -3 pp tolerance; no condition/block loses more than one net eventual correct answer; neither low-load block loses deadline successes; and binding post-progress cuts occur in both pressure conditions. Sustained-pressure deadline gains occur on both shards (+4 and +6). Late burst ties on shard 0 and gains two on shard 1, so its evidence is weaker. Condition/block deltas remain visible in the aggregate rather than being hidden by pooling.

## Latency, costs, and failures

Latencies include late, wrong, and capped responses. These pooled medians/P95 values describe the observed mixtures; P95 is especially sensitive to this small sample.

| Condition | Median client seconds: admission / live | P95 seconds: admission / live | Mean queue seconds: admission / live | Output tokens: admission / live |
| --- | --- | --- | --- | --- |
| Low load | 58.68 / 55.46 | 170.80 / 173.04 | 0.07 / 0.14 | 205,944 / 208,369 |
| Late burst | 143.17 / 127.05 | 279.49 / 266.77 | 100.22 / 92.57 | 138,572 / 135,052 |
| Sustained pressure | 99.57 / 74.64 | 173.01 / 158.05 | 50.35 / 33.49 | 153,044 / 135,036 |

Live generated 434 cue tokens in late burst versus 336 for admission, and 364 versus 238 under sustained pressure; neither generated cue tokens at low load. Total output includes thinking, transitions, answers, and terminators. These counts and end-to-end times include transition costs. **Isolated controller CPU time and instrumentation overhead were not measured**, so this experiment cannot quantify them or production overhead. Goodput remains per job using its own saved calibrated horizon; no rate is pooled over unrelated horizons.

One admission low-load response hit the thinking cap and remains a failure. There were no parser issues or service failures in the measured records. All failures and late completions remain in their original denominators, with no manual score overrides. The four eventual-correctness changes link to raw paired records in [assessment.json](analysis/assessment.json). Matching seeds does not force matching sampled text: low load has no live reductions at all, so its incidental quality gain cannot be attributed to live interruption. Likewise, equal overall accuracy does not prove every intervention harmless.

Mechanics show 27 live reductions, of which 20 bind, across pressure conditions. Both policies use the same initial admission rule, verified before generation. Realized initial budgets match in **134/144 pairs**; downstream queue changes can alter later choices. This is a complete-policy comparison, not an intervention with every downstream decision held constant. Events support an association between live capacity release, shorter queues, and deadline gains; they do not isolate every individual rescue causally.

## Uncertainty and interpretation

The frozen question-cluster bootstrap (10,000 resamples; seed 622205) gives a descriptive sensitivity interval of **+4.17 to +20.83 pp** for the pressure contrast. All repeats of each question move together. This is conditional sensitivity, **not a general serving-population confidence interval**: there are only 24 questions, two shards, shared queues, one model, one hardware class, and one execution per matched phase. Scheduling and sampling variation are not resolved by matching seeds or changing policy order. The observed quality screen is not a 3 pp noninferiority bound.

The supported claim is narrow: under this frozen Qwen3-4B/H100 setup and these workloads, allowing post-admission budget reductions improved correct-by-deadline completion under pressure, predominantly sustained pressure, with equal observed eventual correctness overall and a one-answer pressure quality cost. This result does not show a low-load benefit, establish superiority to prior methods, or establish novelty.

## Execution, recovery, and next step

The six GPU allocations used **18,520 seconds = 5.144 GPU-hours**, including startup, calibration, inference, and drain; the largest took 1:59:58. There were no GPU retries or repair allocations. All six source snapshots, input/trace locks, raw receipts, grades, scheduler archives, hardware records, and allocation accounting are saved under [results/](results/). The archive hashes and lossless raw hashes were rechecked during 5C. The executed source label `fd2fa46` predates the user-requested history squash; immutable source snapshots/hashes preserve provenance independently of that label.

The first CPU aggregation job (6482012) failed because the deployment omitted the unchanged tracked `controlled-comparison/metrics.py`. The local observer separately stopped after connection failures. Neither affected GPU completion. The missing module was restored without changing scientific code, and CPU-only job 6502005 completed the original scoring/aggregation in 56 seconds; its aggregate and all 18 per-run analysis files match local analysis exactly. [Recovery evidence](analysis/postprocessing.json) records the failure, repair, and reproduction check. No GPU experiment was repeated.

The selected 24 questions are now exposed: recorded project exposure is indices 0–99 plus this cohort, **124 unique questions**. The other 376 remain provisionally unused; external/unrecorded use and pretraining remain unknown. The exact updated exposure list is in the diagnostics; the original pre-campaign audit remains historical evidence.

**Next research step:** proceed to 6B's bounded CPU/interface investigation for a paper-based LASER adaptation and fixed-threshold probe control, as specified in [the prior-work plan](../evaluation-plan/PRIOR-WORK.md). Resolve probe/ATP definitions and costs, retain development-only calibration, and address the ACER literature gap before a novelty claim. A later GPU baseline comparison needs its own frozen matched plan and budget. This assessment does not start 6B, tune on the consumed cohort, or authorize another inference campaign.
