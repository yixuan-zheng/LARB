# Experiment 1 · Full-prefix prediction results

**Decision: inconclusive under the frozen Stage 1 criterion.** Full-prefix forecasts yielded **52 expected correct answers versus 47** for question-only at the same extension counts. The pooled lift was **+5 answers (+4.35 percentage points)** with a question-clustered 95% interval of **−0.88 to +9.57 points**. The point estimate cleared the practical minimum of four answers, but the interval included zero and the Week 7 estimate was negative.

## Fixed-budget comparison

| Cohort | Eligible | Extensions | Question-only correct | Full-prefix correct | Lift | 95% interval |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Week 6 | 57 | 28 | 21 | 27 | +6 (+10.53 pp) | +1.75 to +19.30 pp |
| Week 7 | 58 | 29 | 26 | 25 | −1 (−1.72 pp) | −6.90 to +3.45 pp |
| Pooled | 115 | 57 across cohorts | 47 | 52 | +5 (+4.35 pp) | −0.88 to +9.57 pp |

Expected counts reflect fractional uniform selection at cutoff ties, evaluated on the saved single-suffix correctness transitions. The frozen scorer used 10,000 paired, cohort-stratified question bootstraps, keeping seeds together and recomputing the half-allocation within each resample.

## Prediction diagnostics

| Cohort | Gains captured, question → prefix | Losses captured, question → prefix | Gain AUC, question → prefix | Joint Brier, question → prefix |
| --- | ---: | ---: | ---: | ---: |
| Week 6 | 1 → 7 | 0 → 0 | 0.181 → 0.676 | 0.853 → 0.720 |
| Week 7 | 5 → 4 | 0 → 0 | 0.756 → 0.652 | 0.866 → 0.846 |

Full-prefix scores ranked the higher realized net-benefit seed first in **3 of 4** discordant Week 6 questions and **4 of 5** Week 7 questions. Question-only assigns both seeds the same score. The nine discordant pairs provide limited evidence about trajectory-specific ranking. Joint Brier improved in both cohorts, while gain AUC and allocation yield moved in opposite directions across cohorts. Per-transition reliability bins are in `RESULTS.json`.

The full-prefix reader averaged **4,651 prompt and 3,990 completion tokens** per request, versus **409 and 3,706** for question-only. The question-only forecast is also reused across seeds. At the fixed extension counts, the full-prefix allocations used about **38,902 additional archived generator tokens** across both cohorts because they selected different trajectories. With uncertain pooled lift and opposite cohort effects, these results do not establish that the added reader compute is justified.

## Engineering and provenance

A100 recovery job **7020297** completed in **11m 44s**. The one exact retry of `case-169` passed the original output contract. Its original malformed response remains archived, with no normalization or alternate-seed selection. CPU job **7020298** verified the complete seal and raw hashes before opening the outcome join. Local verification independently rechecked all 174 request identities, response validity, and archive hashes.

Forecast seal SHA-256: `ada8b91faabe7b4823d01a8999d722715dd37912b1b7f21fb0b35fd48b7ee888`.
