# Stage 1 results: normal Qwen3 reasoning

October 16, 2026. PACE job `6303281`, one NVIDIA L40S.

## What we established

Qwen3-4B runs successfully on the available GPU and produces a thinking block followed by a separate final answer. On ten MATH-500 problems, nine returned correct final answers. One kept reasoning until the safety cap and returned no final answer. The baseline is ready for preliminary budget experiments, with that failure retained.

## Setup

- Model: `Qwen/Qwen3-4B`, bf16, PyTorch 2.9.1+cu128, Transformers 5.7.0, SDPA attention.
- Workload: the first ten rows of a pinned MATH-500 revision, run sequentially. This is a development smoke test, not a balanced or held-out accuracy evaluation.
- Thinking enabled through the normal chat template. No thinking cutoff, injected answer transition, load controller, or non-thinking comparison.
- Sampling: temperature 0.6, top-p 0.95, top-k 20; seeds 6222–6231. These settings follow the [official model guidance](https://huggingface.co/Qwen/Qwen3-4B).
- Safety cap: 16,384 generated tokens total, including thinking and final answer. Requests hitting it remain failures in the accuracy denominator.
- Prompt: the original problem plus a request to put the final answer in `\boxed{}`. Reference answers and solutions were not sent to the model.
- Timing: CUDA-synchronized generation wall time after a short warmup. Downloads, model loading, tokenization, and queueing are excluded. This is not serving throughput or time to first answer token.

## Results

| Problem | Topic | Thinking tokens | Total output tokens | Time (s) | Reviewed result |
| --- | --- | ---: | ---: | ---: | --- |
| 1 | Polar coordinates | 1431 | 1,723 | 42.84 | Correct |
| 2 | Double infinite sum | 6582 | 7,258 | 160.93 | Correct |
| 3 | Rational function evaluation | 1973 | 2,356 | 51.84 | Correct |
| 4 | Divisors of 196 | 1501 | 2,102 | 46.14 | Correct |
| 5 | Average speed from graph source | 3245 | 3,827 | 84.15 | Correct |
| 6 | Hexagon perimeter | 3238 | 3,633 | 79.84 | Correct |
| 7 | Cube as three consecutive integers | 3063 | 3,568 | 78.69 | Correct |
| 8 | Angle between lines | 3420 | 4,180 | 99.74 | Correct |
| 9 | Distance between points | 1546 | 1,878 | 42.05 | Correct |
| 10 | Parenthesization values | Unclosed* | 16,384 | 368.74 | No final answer; cap hit |

*Problem 10 generated an opening thinking marker but no closing marker. All 16,384 output tokens were before any final-answer boundary; no completed thinking length is available.

- **Reviewed accuracy / final-answer success: 9/10 (90%).**
- Raw whitespace-normalized exact matches: 5/10. Four correct answers differed only in LaTeX formatting or degree notation. Those decisions are recorded separately in `manual-review.json`.
- Median generation time: **79.26 seconds**. Range: **42.05–368.74 seconds**.
- Among the nine normal completions, thinking lengths ranged from **1,431 to 6,582 tokens**, with a median of **3,063**.
- Thinking occupied **85.2% of output tokens among normal completions**. This is a token fraction, not a directly measured fraction of execution time.
- The capped request consumed **35.0% of total generation time** across the ten requests.
- Total measured generation time: **17 minutes 35 seconds**. Successful GPU allocation: **18 minutes 45 seconds**.

## What the outputs look like

Normal outputs open a `<think>` block, work through the problem, close it with `</think>`, and then produce an explanatory answer ending in a boxed result. We verified the boundary in the saved token IDs and text. Final answers can themselves be several hundred tokens long.

On the polar-coordinate problem, the model worked through the formulas, checked the axis and quadrant, and revisited the answer using another formulation. It then returned the correct coordinates. Even this simple problem used 1,431 thinking tokens and about 43 seconds.

On the double-sum problem, it reindexed the sum, checked the expression numerically, and revisited the derivation before returning the correct `p - q`. That request used 6,582 thinking tokens and about 161 seconds.

The parenthesization problem failed to finish. Inspection of its output shows repeated attempts to enumerate possibilities, including invalid variants that move the addition operator. This is a substantive reasoning failure in the observed run, not merely an answer-formatting problem. We cannot tell whether allowing more tokens would eventually recover a correct final answer.

## What this means for the next step

We now have a reproducible baseline runner, inspectable model outputs, and measured variation in reasoning length and completion time. The next small experiment can test fixed thinking budgets against these same development prompts. It must preserve a separate final-answer phase and count missing answers as failures.

The long failed request shows that a substantial amount of time can be spent without obtaining an answer. It does not show that cutting thinking would preserve accuracy. There is no evidence yet that mid-request control beats arrival-time budgets.

## Saved evidence and checks

- [Manifest](results/job-6303281/manifest.json): exact model/data revisions, seeds, settings, runtime, and `completed=true`.
- [Per-request records](results/job-6303281/requests.jsonl): raw output, token IDs, timing, and preliminary scores.
- [Readable transcripts](results/job-6303281/transcripts.md): all ten prompts and complete generated text.
- [Manual answer review](results/job-6303281/manual-review.json): each correctness decision and explanation.
- Executed source and launcher are archived in the run directory. The current runner additionally defaults to the recorded revisions for future runs.
- Validation checked ten contiguous request indices, token-count conservation, positive timings, final-answer boundaries, and completion status.
- Python compilation and shell syntax checks passed. No additional model runs were needed for these checks.
- Initial job `6303266` failed before inference because the loader expected Parquet rather than JSONL. It used 51 seconds of GPU allocation; its failed-launch log is omitted from this package; the allocation is recorded here. The corrected job completed successfully. Combined allocation was 19 minutes 36 seconds.
- The existing Gemma environment was reused without package changes. Qwen model cache and experiment files are separate. An isolated PyArrow install from the initial loader attempt remains unused by the final runner.
- Both jobs have exited. No experiments remain running.
