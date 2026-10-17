# Stage 3 preliminary comparison

The experimental settings in `protocol.json` were fixed before the successful sweep submission (`6307328`). The scheduling notes below also record later orchestration changes; they do not change generation or scoring settings.

## Question

Can a fixed shorter thinking budget preserve nearly all of full-thinking accuracy while reducing completion time substantially? Also check whether non-thinking mode already provides the useful tradeoff.

## Workload and configurations

Use the first 100 problems from pinned MATH-500 revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be`. The first ten were already used in Stages 1 and 2. These are development examples; the other 400 are not evaluated.

Use the same Qwen3-4B checkpoint, problem text, boxed-answer instruction, sampling settings, and per-problem seeds for every configuration:

- Full thinking, with a 16,384-token safety limit on an unclosed thinking phase.
- 256, 512, 1,024, and 2,048 normal pre-close tokens, followed by the fixed Stage 2 finalization cue and closing marker.
- Non-thinking mode through the chat template's `enable_thinking=False` setting.

All modes receive a separate 2,048-token answer allowance. The cue's 14 forced tokens are additional to the normal thinking allowance and their execution is timed. The pre-close budget includes the opening marker and whitespace, as in Stages 1 and 2.

Temperature 0.6, top-p 0.95, and top-k 20 are identical across modes to isolate the mode/budget change. This does not separately tune sampling for non-thinking mode.

## Measurements

Primary accuracy is the fraction of all 100 problems producing a correct final answer and a normal end-of-response token. Missing answers and cap hits count as failures. Report correct boxed answers regardless of completion as a separate secondary measure.

Use canonical exact matching followed by pinned Math-Verify 0.9.0 mathematical equivalence. Review extraction and parser ambiguities. Never grade reasoning text as a final answer. A correct intermediate expression does not make an unfinished response a primary success.

Measure total generation time from the original prompt through the answer. Include transition and observation overhead. Exclude model loading, warmup, tokenization, and scheduler waiting. Report median, mean, p95, and cap counts. Every mode uses the same instrumented, sequential Transformers execution path on L40S GPUs.

## Preliminary decision

A configuration passes the point-estimate screen if it is within 3 percentage points of full-thinking primary accuracy and has at least 25% lower median completion time. Show paired per-problem bootstrap intervals; a 100-problem development screen does not establish a general 3-point quality floor.

Compare passing thinking budgets with non-thinking mode as well. A cheap fixed mode that already wins weakens the case for adding load adaptation.

Full thinking is bounded by a safety cap, not unlimited. If full-thinking cap failures materially affect the comparison, report that limitation rather than presenting a capped-baseline win as proof of preserved unlimited-thinking quality.

## Execution and reproducibility

Thirty resumable tasks each process 20 requests. Task number modulo six selects the configuration; integer division by six selects the problem shard. At most six L40S GPUs run concurrently. The first full-thinking task allows three hours; the remaining full-thinking tasks use one-hour reservations to improve scheduling, with checkpointed resumption if needed. Scheduler limits for backfilling are 30 minutes for 256/512/non-thinking tasks, 45 minutes for 1,024, and one hour for 2,048. These reservation changes do not change token allowances or generation settings.

Each task records the protocol hash, source hashes, exact model/data revisions, node, GPU, seed, complete outputs, token IDs, timing, and finish reasons. Per-request records are written atomically and partial tasks can resume without rerunning finished requests. All 600 records must be present before a final comparison is reported.

To reduce the tail of the run, later short shards were made eligible after full-thinking tasks 18 and 24 start. Slurm releases them automatically on those start events. The task mapping and six-GPU concurrency cap remain unchanged.
