# Reserved validation results

2/6 stages collected and graded. The complete-campaign decision is made only after all six matched stages. Correctness does not gate continuation.

| Stage | Condition / shard | Admission on time | Live on time | Admission eventual | Live eventual | GPU time |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | late_burst / 0 | 7/24 | 7/24 | 23/24 | 23/24 | 24:00 |
| 2 | sustained_pressure / 0 | 13/24 | 17/24 | 24/24 | 23/24 | 27:21 |

Each stage has 12 unique questions replayed twice; all stages together cover only 24 unique questions. Caps, late completions, and wrong answers stay in the denominator. Each run directory includes raw responses, source/input/trace hashes, a mechanical audit, grades, review queue, and accounting.

No controller changes, quality-driven retries, or question substitutions were made. Intermediate rows are partial results and do not select later stages. The frozen [plan](../evaluation-plan/EVALUATION.md) explains the endpoints and uncertainty.
