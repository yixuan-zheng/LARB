# Experiment 2 | Repeated continuation sampling results

All **928 planned draws** completed across 58 saved Week 7 prefixes from 29 AIME 2026 questions. Each exact 4K checkpoint supplied eight independently seeded short draws and eight long draws. The short policy forced the answer at 4,096 reasoning tokens. The long policy allowed natural closure or forced the answer at 8,192. Both used pinned Qwen3-4B BF16 and the same legacy answer allowance and boxed-integer grader. The 12 integrated gate draws were included in the frozen schedule.

## Main result

| Policy | Correct draws | Estimated correctness | Answer-cap stops | Mean suffix wall time |
|---|---:|---:|---:|---:|
| Answer at 4K | 167/464 | 36.0% | 113 | 22.22 s |
| Continue up to 8K | 230/464 | 49.6% | 57 | 77.19 s |

Mean **p8 − p4 was +13.6 percentage points**. The frozen question-cluster bootstrap interval was **+5.8 to +22.4 points**, with both prefixes for each question kept together. The interval resamples question groups conditional on the measured draws. The estimate applies to the archived prefixes that were still reasoning at 4K and the specified decode and grading policy. The longer arm incurred fewer answer-cap stops, so this is the net effect of the budget policy under the shared answer allowance. The comparison does not isolate how much of the effect came from solving more problems versus completing the answer phase.

## Variation across checkpoints

- **19/58** prefixes had a positive observed difference, **37/58** tied, and **2/58** had a negative difference. Among ties, 21 went 0/8 in both arms and 16 went 8/8 in both. These are observed counts from eight draws per arm. Equal counts leave uncertainty about the true probability difference.
- Three prefixes had approximate per-prefix 95% intervals for the difference wholly above zero. `q02-b1` and `q21-b1` went from 0/8 to 7/8, and `q19-b1` went from 1/8 to 8/8. These intervals are unadjusted across the 58 prefixes. Both negative observed differences were −1/8 and their intervals included zero.
- Under the specified independent-draw convention, mean estimated wrong-to-right probability was **14.5%** and right-to-wrong probability was **1.0%**. Their difference is the marginal correctness gain. The joint probabilities describe independently sampled answers and do not identify what would have happened under shared sampling randomness.

Repeated sampling supports a positive average benefit and shows that the observed gains were concentrated. Eight draws per arm move each per-prefix probability in 12.5-point steps. Treat the per-prefix estimates as noisy reference targets for the separately planned question-disjoint prediction test. A positive average effect alone says little about whether a pre-checkpoint predictor can allocate extensions well. These measurements also leave serving goodput open.

## Execution and reproduction

Five serial L40S jobs completed in **13h 16m 20s** of allocation time in total, followed by 25 seconds of CPU grading. The calls generated **2,994,681 suffix tokens** and processed **3,932,384 input tokens** including re-prefills. All 928 draw records matched the frozen schedule and token hashes in local scoring. The recomputed JSON matched the PACE summary byte for byte. There were zero missing draws. The scorer counted 170 answer-cap stops and 33 normal completions with invalid answer boxes as incorrect.

[Per-prefix p4, p8, intervals and all grades](results/full-summary.json) · [Run manifest](results/run/manifest.json) · [Engineering gate](results/run/engineering-gate.json) · [Frozen specification](SPEC.md)
