# Stage 3: find the reasoning-budget sweet spot

October 16, 2026. Qwen3-4B, the same 100 MATH-500 development problems, six configurations, 600 attempts.

## Decision

**No tested shorter budget passed our preliminary screen. Pause before building load adaptation with this model and cutoff method.**

Full thinking answered **95/100** correctly. Our three-percentage-point tolerance therefore required **at least 92/100**, together with at least 25% lower median runtime. The best budgeted accuracy was **90/100 at 2,048 tokens**. It reduced median runtime by **26.5%**, but lost **5 percentage points of accuracy**. Smaller budgets saved more time and lost more accuracy.

## Results

Times are seconds per request. Every column includes all 100 attempts, including cap failures. Accuracy requires a correct final answer and normal end-of-response.

| Configuration | Correct / 100 | Accuracy change vs full | Median time | Mean time | P95 time |
| --- | ---: | ---: | ---: | ---: | ---: |
| Full thinking | 95 | — | 74.5 | 102.7 | 354.5 |
| 256 tokens | 87 | -8 pp | 15.1 | 19.6 | 44.4 |
| 512 tokens | 87 | -8 pp | 21.0 | 25.0 | 48.3 |
| 1,024 tokens | 89 | -6 pp | 32.7 | 36.0 | 55.5 |
| 2,048 tokens | 90 | -5 pp | 54.7 | 52.7 | 73.9 |
| Non-thinking | 85 | -10 pp | 9.4 | 14.8 | 44.4 |

[View the accuracy/time plot](stage3/analysis/accuracy-time.png). The target region requires at least 92% accuracy and median runtime no greater than 55.8 seconds. No tested point falls inside it.

## What failed

The time savings are real in this setup: median reductions range from **26.5% to 79.7%** across the four thinking budgets. The limiting factor is answer accuracy.

At 2,048 tokens, **99/100 responses finished normally**, but nine completed answers were wrong and one response hit the answer cap. Full thinking had one wrong completed answer and four thinking-cap failures. More reliable response completion did not preserve mathematical accuracy. The secondary measure, correct boxed answers regardless of normal completion, gives the same scores in this run.

The full baseline already counts its four safety-cap failures as incorrect. That makes the observed five-point gap to the best shorter budget conservative with respect to any additional correct answers obtained by extending full thinking.

## How the comparison was run

- Pinned `Qwen/Qwen3-4B` revision `1cfa9a7208912126459214e8b04321603b3df60c`, bf16, SDPA, PyTorch 2.9.1+cu128, Transformers 5.7.0, NVIDIA L40S.
- First 100 rows of pinned MATH-500 revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`. The first ten were used in earlier development; the other 400 dataset examples were not evaluated.
- Identical problem text, boxed-answer instruction, temperature 0.6, top-p 0.95, top-k 20, and per-problem seeds 6222–6321. One sampled response per configuration and problem. Sampling was not separately tuned for non-thinking mode.
- Budgeted modes use the fixed Stage 2 finalization cue and `</think>` in the same generation call and KV cache. Each budget counts normal pre-close generated tokens, including the opening marker and whitespace. The 14 injected transition tokens are additional and timed.
- Full thinking uses a **16,384-token safety limit** on an unclosed thinking phase. All modes have a separate **2,048-token answer allowance**. Non-thinking mode uses the chat template’s `enable_thinking=False`.
- Timings cover synchronized generation after warmup, including transition and observation overhead. Loading, tokenization, and cluster queue time are excluded. These are sequential Transformers measurements; serving performance is a later question.

## Scoring checks

Answers were checked using canonical formatting normalization followed by [Math-Verify 0.9.0](https://pypi.org/project/math-verify/0.9.0/). All wrong boxed answers and nontrivial equivalent forms were inspected. There were no parser exceptions and no normally completed responses missing a boxed answer.

Last-box extraction missed **six correct final-answer groups** where the model boxed each member separately. We recorded those corrections in [manual-review.json](stage3/manual-review.json), with explanations and raw-record hashes: two in full thinking, and one each in 256, 512, 1,024, and non-thinking mode. The 2,048-token score needed no correction.

This matters for the comparison: full thinking’s automated last-box score was 93/100, but its mathematically correct reviewed score is **95/100**. The full responses explicitly gave the complete correct solution sets at dataset indices 25 and 36. The report uses reviewed scores consistently for every mode; original automated scores remain saved.

## What the uncertainty allows us to say

This is a development screen with one sampled response per problem. For the 2,048-token configuration, the paired-bootstrap 95% interval for the accuracy change is **−10 to 0 percentage points**; its median-time reduction interval is approximately **7.7% to 34.4%**. The sample does not establish the exact population gap or a general quality guarantee.

The concrete result is that **none of the four thinking budgets or non-thinking mode meets the observed 92/100 quality floor**. The 2,048-token setting is the closest budgeted candidate, but it does not satisfy the agreed screen. The recommendation applies to this model, transition cue, and tested budget grid.

## Validation and saved evidence

- All **600 unique configuration/problem pairs** are present, with 100 per mode and all 30 task manifests complete.
- Generation source hashes, protocol hash, runtime versions, and GPU type match across shards. Cap lengths and token-count conservation were checked.
- All **400 pre-cutoff prefix comparisons** match full thinking. No response reopened a thinking marker.
- Five controller unit checks passed, including non-thinking answer allowance. Python and launcher syntax checks passed. The final plot was visually checked.
- Successful array `6307328` used **7.41 L40S GPU-hours**, with at most six GPUs active. Its first allocation to final exit spanned **1 hour 27 minutes 49 seconds**. All 30 tasks exited successfully; no experiment jobs remain running.
- Initial submission `6307312` failed during protocol-file loading before model inference. It contributed no evaluation records; the corrected matrix is complete and independent.

Files:

- [Frozen settings and dataset](stage3/protocol.json), [readable protocol](stage3/PROTOCOL.md), and [validation summary](stage3/validation.json).
- [Summary CSV](stage3/analysis/summary.csv), [full statistics and paired intervals](stage3/analysis/summary.json), and [per-problem scores](stage3/analysis/per-problem.csv).
- [Graded records](stage3/scores/graded.json), [grading environment](stage3/scores/grader-manifest.json), and [analysis environment](stage3/analysis/analysis-manifest.json).
- [Raw task outputs and executed source](stage3/results/), [scheduler accounting](stage3/accounting.txt), and [analysis dependency pins](stage3/requirements-analysis.txt).
