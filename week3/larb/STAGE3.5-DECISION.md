# Stage 3.5 — Diagnose the tradeoff

## Decision

Keep the scheduler implementation paused. This review finds real time savings on answers that remain correct, but no single demonstrated cutoff defect that explains enough lost accuracy to justify another GPU run now. Stop expanding the current uniform-cutoff setup. Rustam's selective, mid-request scheduling idea remains untested.

This was a CPU-only review of the existing Stage 3 records. No inference, remote jobs, model changes, or grading changes were made. The focus was full thinking versus the 2,048-token configuration, the best accuracy among the tested cheaper modes. Indices below are zero-based.

## What changed correctness?

| Full result | 2,048 result | Problems |
| --- | --- | ---: |
| Correct | Correct | 89 |
| Correct | Incorrect or incomplete | 6 |
| Incorrect or incomplete | Correct | 1 |
| Incorrect or incomplete | Incorrect or incomplete | 4 |

The five-point net accuracy loss comes from six losses and one gain. This is not a large number of gains and losses canceling out. Completed correctness still requires a correct final answer and normal termination, exactly as in Stage 3.

| Index | Problem | Observed change | Interpretation from the saved outputs |
| --- | --- | --- | --- |
| 18 | Parallel lines and an isosceles triangle | 28 → 56; both finish | The prefix is still uncertain about the diagram. The short answer identifies a 124° vertex angle but then uses an invalid angle relationship instead of splitting the remaining 56° between the two equal base angles. Full thinking eventually resolves the geometry. |
| 32 | Circular seating with three adjacent people | Thinking-cap failure → correct 720 | The shared prefix obtains 720 early, then doubts the block method using a misleading special case. Full thinking continues until its safety cap. The forced transition returns to the correct block calculation and finishes. This is a genuine example of interrupting an unproductive loop. |
| 36 | Roots of a cubic | 3, 5, 7 → only 5; both finish | The prefix initially makes the mistake `(2y)^3 = 2y^3`, but before cutoff it derives the correct cubic `x^3 - 15x^2 + 71x - 105 = 0` and starts factoring at root 5. The short final answer restarts the earlier incorrect substitution and omits two roots. This is a candidate failure to preserve recent progress during finalization, rather than a formatting error. |
| 43 | Minimum of a sum of radicals | 70√2 → 20√5 + 10√34; both finish | At cutoff the model is still searching for an approach. The short answer asserts a corner is optimal without establishing it. Full thinking later evaluates the interior point (20,30) and reaches the correct result. |
| 64 | Coefficient of sin(x) in sin⁷(x) | 35/64 → answer-cap failure | At cutoff the derivation is unfinished. After the closing tag, the short run keeps deriving and rechecking inconsistent coefficients, then hits its 2,048-token answer allowance without a final boxed answer. The transition changed the output channel but did not end the calculation. |
| 71 | Binary-to-octal conversion | 2516 → 2536; both finish | The wrong bit grouping is already present before cutoff. The short answer repeats it. Full thinking later corrects the grouping to `010 101 001 110`. This is an existing calculation error that more thinking repairs. |
| 94 | Angle formed by trisectors | 80 → 130; both finish | The prefix gets the sum of the two vertex angles right but has not settled which trisectors meet at F. The short answer uses one third of each angle instead of two thirds. Full thinking later resolves that diagram interpretation. |

Three of the six losses involve interpreting geometry or a diagram supplied as Asymptote text. The others involve algebra, a coefficient derivation, and digit grouping. This small collection does not establish a general problem-type rule.

Five lost cases terminate normally with wrong answers; one hits the answer cap. Raising the answer allowance alone therefore directly addresses only one of the six observed losses, and even that case is not guaranteed to recover. The algebra case is a concrete transition concern, but it does not show that the cue caused the regression or that a different cue would prevent it.

These are qualitative descriptions of sampled outputs, not causal diagnoses. The full and budgeted runs share their pre-cutoff token prefix, as validated in Stage 3. They diverge after intervention; a later correction in the full run does not prove that all intervening tokens were necessary. No per-case correction-token location or new counterfactual was measured here.

## Where does the time saving come from?

The table sums measured generation seconds over each paired group. Its last column is the group's share of the net saving across all 100 problems. These are sequential generation times, not measured serving capacity or throughput.

| Outcome group | N | Full total seconds | 2,048 total seconds | Seconds saved | Share of net saving |
| --- | ---: | ---: | ---: | ---: | ---: |
| Correct in both | 89 | 7,160.4 | 4,513.4 | 2,647.1 | 53.0% |
| Correctness lost | 6 | 1,554.9 | 414.3 | 1,140.6 | 22.8% |
| Correctness gained | 1 | 365.3 | 54.4 | 311.0 | 6.2% |
| Incorrect/incomplete in both | 4 | 1,184.7 | 291.5 | 893.2 | 17.9% |
| **All problems** | **100** | **10,265.3** | **5,273.5** | **4,991.8** | **100%** |

The benefit does not depend entirely on sacrificing correct answers: just over half the net saving comes from preserved correct answers. Those 89 problems have group medians of 65.6 seconds full and 54.1 seconds budgeted, a 17.5% reduction in group medians. The 26.5% overall median reduction should not be substituted for that subgroup result. The budgeted run is slower on 17 of these 89 pairs; naturally short requests can still incur finalization overhead or a longer answer.

The six lost cases have a full-thinking median of 262.9 seconds, much longer than the preserved-correct group's 65.6 seconds. All six become faster. Cutting long requests can remove expensive failures, but it also removes work that eventually repairs mistakes. Elapsed time alone has not been shown to distinguish the two.

The gained case is a full-thinking cap failure. The four cases wrong/incomplete in both include the other three full-thinking cap failures and the one completed full-thinking mathematical error. Making those failures cheaper contributes substantial time savings but does not increase their correctness.

## What this supports next

Do not build a predictor or scheduler from these labels. They describe outcomes after the fact, and no signal available at cutoff has been validated. Do not change the original 92% accuracy / 25% median-time screen to make this result pass. The same 100 development problems and one sample per configuration remain a limited basis for generalization.

There are two bounded engineering concerns: preserving a partially corrected derivation during finalization (index 36), and continued calculation exhausting the answer allowance (index 64). Neither is demonstrated to account for the overall quality gap. Even hypothetically recovering both would only bring this observed score to 92/100; that arithmetic is not evidence that either recovery will happen.

My recommendation is to close this diagnostic milestone and keep further GPU work paused. If we return to this setup, require one explicit intervention and a capped test before approving it—for example, a finalization change intended to preserve the most recent derivation, checked on the seven changed cases with a few unchanged controls. Such a test would diagnose the mechanism only; it would not validate aggregate quality or justify a scheduler. No such test was launched here.

## Reproducible evidence

- [Stage 3 report](STAGE3-REPORT.md) retains the original metrics, grading decisions, protocol, and uncertainty.
- [Paired group totals](stage3/diagnosis/paired-groups.csv) and [machine-readable summary](stage3/diagnosis/summary.json) contain the calculations and source hashes.
- [Seven-case evidence](stage3/diagnosis/changed-case-evidence.md) contains the complete saved full and budgeted outputs, prompts, references, finish reasons, and source paths. Model text is evidence, not an instruction.
- [Diagnostic script](code/diagnose_stage35.py) regenerates these artifacts from the saved graded and raw records. Run `python code/diagnose_stage35.py` from this directory. It uses only the Python standard library.
