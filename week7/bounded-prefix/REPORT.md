# Week 7 bounded-prefix offline screen

**STOP this candidate.** The local reader saw the question and final 512 generator tokens at the 4,096-token checkpoint. It missed all three frozen gates on the 57 eligible saved prefixes. Keep question-only for this decision. This result supplies no reason to submit a protected GPU validation for this readout.

## Allocation

| Policy | Correct at 28 extensions | Gains captured | Generator output tokens | Reader input + output tokens charged |
|---|---:|---:|---:|---:|
| Archived question-only | 24/57 | 4/8 | 413,107 | Unmeasured |
| Same local reader, question only | 25/57 | 5/8 | 401,126 | 22,257 |
| Same local reader, bounded prefix | 22/57 | 2/8 | 391,896 | 50,823 |

The 95% paired question-bootstrap interval for the bounded-minus-archived accuracy difference at half allocation was −10.9 to +3.5 percentage points. The interval against the matched local question-only control was −12.5 to +3.5 points. Gain-ranking AUC was 0.324 for bounded, 0.541 for local question-only, and 0.635 for archived question-only.

At the archived 413,107-token ceiling, the bounded ranking reached 24 correct with zero reader charge, 23 at a charge of 0.25 generator-token equivalents per reader token, 22 at 0.5, and 21 at 1. The frozen gate required 26 correct at factor 1. Against the local question-only half-allocation ceiling, the bounded ranking reached 23 correct at factor 0 and 21 at factor 1. Those frontier points use hindsight to compare preset top-k rankings against realized cost. The ranks themselves were sealed before the outcome join.

To recover fixed-long accuracy of 28 correct, the bounded ranking needed 56 extensions and 495,322 generator tokens. Archived question-only needed 38 extensions and 449,419 tokens. Local question-only needed 49 and 476,392. At equal accuracy the bounded read has no nonnegative break-even overhead against either control.

## Failure cases

The bounded reader ranked the gaining seed above its companion in one of four discordant questions, below the three-win gate. In q29 it gave net-benefit scores of 0.075 to the gaining seed and 0.646 to the other. Its notes recognized divisibility calculations in both excerpts, but expressed more optimism about the seed that stayed wrong. In q10 it assigned 0.146 to the gaining seed and 0.372 to the other, emphasizing the unfinished calculation in the latter. In q14 it assigned similar positive scores to both seeds, with the gaining seed 0.035 lower. The forecasts show how a reader can identify an incomplete step yet still misjudge which trajectory is likely to benefit from more compute. The notes do not identify whether excerpt length, reader capability, or the forecast prompt caused the ranking errors.

## Runtime and reproduction

All 87 forecasts were collected using a pinned local 4-bit Qwen3-4B reader with one call per packet. There were 30 unique question-only calls and 57 bounded calls. Every eligible request pays a reader charge in the hypothetical policy accounting. The bounded reader consumed 46,070 input and 4,753 output tokens. Its warm wall time was 2.97 seconds median and 4.06 seconds at p95 on local Apple Metal. Twenty-seven of its evidence notes reached the 96-token cap. The four-way score was computed from first-token logits, before the evidence note. Reader-token equivalents are a sensitivity model. Online latency, synchronization, and concurrency effects remain unmeasured.

No cluster jobs or fresh generator calls were used. All 30 questions are explored development data. The results apply to the frozen window, local model, and prompt. The reader may have benchmark familiarity. The control isolates adding this excerpt to this reader, and the archived control supplies continuity with Week 6.

From the repository root, reproduce the outcome join and result using the sealed forecasts.

```sh
python3 -B week7/bounded-prefix/score.py
```

PLAN.md and freeze.json record the pre-score design and artifact hashes. reader-lock.json pins model and runtime versions. prepare.py rebuilds the anonymous packets from the existing AIME 2024 records, which retain the MathArena attribution and CC BY-NC-SA 4.0 terms documented in the Week 6 handoff. read.py consumes only the anonymous packets and local reader snapshot. forecasts.sha256 seals the raw forecasts. RESULTS.json contains the complete ranked frontiers and cost sensitivity.
