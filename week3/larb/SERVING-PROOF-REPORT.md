# Live thinking-budget changes: serving proof

## Result

**Mid-request budget changes work in real concurrent vLLM serving in this pinned setup.** An active request received a lower budget, emitted the existing Stage 3 transition cue, continued into its final answer, and completed without a restart. A waiting request then used the freed slot while another request remained active.

Job **6309923** completed with exit code **0:0**. All **18 automated checks passed**. The single H100 allocation lasted **233 seconds (3 minutes 53 seconds; about 0.065 GPU-hours)**, including startup and validation. There were three measured model requests, no inference retries, and no burst-policy comparison. The account queue was empty after completion.

This resolves the core engineering uncertainty that blocked the small burst pilot. It does not resolve the Stage 3 accuracy tradeoff or demonstrate a serving-performance advantage.

## What ran

- Qwen/Qwen3-4B, revision `1cfa9a7208912126459214e8b04321603b3df60c`, loaded offline from the existing cache, BF16.
- vLLM 0.11.2, Torch 2.9.0, Transformers 4.57.6; separate environment, original experiment environment unchanged.
- Real loopback HTTP streaming service backed by the asynchronous vLLM V1 engine and its continuous batching. Maximum two active sequences; three clients submitted overlapping requests.
- Eager execution, FlashAttention, standard sampler, no speculative decoding, prefix caching disabled. Existing sampling settings, 16,384-token thinking safety limit, 2,048-token post-close answer allowance, and exact Stage 3 cue retained.
- One H100 on `ice-gpu`, same `coc` account and `coc-ice` QoS. The job was initially queued for an L40S, then moved before allocation because the usable L40S nodes were occupied. Its allocation ceiling was reduced to 15 minutes. This is not a timing comparison with the earlier L40S experiments.

The inputs were development problems 1, 0, and 2, selected for this engineering demonstration using the prior completion records. They are not an unbiased accuracy sample. The initial geometry input in the draft was replaced before GPU execution because its earlier short-budget response had exhausted the answer cap; that selection is documented in the adapter README.

## Observed sequence

1. A, the summation problem, began with a 16,384-token allowance.
2. After A had streamed 128 tokens, B, the polar-coordinate problem, was submitted. The scheduler records show A and B being processed together.
3. After B had streamed 64 tokens, C, the rational-function problem, was submitted. It waited while both slots were occupied.
4. After the client saw at least 512 A tokens, it called `/budget/A` with a budget of 512. The GPU worker observed the update with **513 tokens already generated**. The one-token overrun was in flight; the update does not delete previously generated tokens.
5. A began the exact 14-token Stage 3 cue at generated position **513**. The closing marker was at zero-based position **525**. A then produced its answer and ended naturally, with **1,268 total output tokens** and final answer **p − q**.
6. C was admitted to A's released slot while B was still active. It did not inherit A's reduced budget.
7. B closed thinking naturally. A subsequent `/budget/B` update to 1 was observed and ignored, without reopening thinking or injecting another cue.
8. B and C both completed naturally. None of the requests hit the answer allowance or reopened thinking.

| Request | Thinking closure | Tokens after closing marker, including terminal token | Final boxed answer |
| --- | --- | ---: | --- |
| A | Forced after live update | 742 | p − q |
| B | Natural | 383 | (3, π/2) |
| C | Natural | 389 | 14/3 |

All three boxed answers match these three references by inspection. This is completion evidence for a selected mechanism check, not a new estimate of model accuracy.

The command file write to worker observation took about **6.5 ms**, and write to first forced-cue sampling about **18.4 ms** in this run. The observed update and cue start had the same generated-token count. These instrumented single-run measurements are not a latency guarantee.

## Why this is an in-place update

The service submitted each request exactly once. The worker admitted each request exactly once. A retained the same worker output-list object across admission, budget observation, cue start, and closure.

More importantly, 4,312 scheduler snapshots cover the run. Computed-token counts remained monotonic; allocated KV block lists retained their existing prefixes as they grew; preemption counts stayed zero. The trace spans A before and after its update. Combined with the unmodified generation engine and the adapter's logits-only intervention, this supports continuation with retained cache, without abort/resubmit or prefix replay.

Cache evidence concerns allocation and computation history, not a bitwise comparison of cache tensors. The real run exercised row replacement when C took A's slot. It produced no row-move events; swaps and moves are covered by the separate CPU tests, not claimed as exercised on GPU here.

## Implementation and limits

The minimal control adapter uses vLLM's custom logits-processor extension. Request keys and initial settings travel in `SamplingParams.extra_args`. The HTTP control endpoint atomically replaces a JSON mailbox; the worker reads it at sampling boundaries and changes only the matching request's state. It forces the cue token by token, then resumes ordinary sampling.

No engine source was modified and no new batching scheduler was implemented. The read-only audit subclass delegates all decisions to the stock scheduler, recording request progress and KV allocations. That audit uses version-specific private scheduler attributes; it is not a stable production API. The control mechanism itself does not need that audit subclass to operate.

File polling, per-step tracing, and eager execution favor inspectability over speed. This implementation is sufficient for a tightly bounded preliminary pilot, not an optimized service. The test drove the update explicitly through an endpoint; it did not test an automatic pressure policy, deadlines, throughput benefits, or the advantage over arrival-only budgets.

**Next decision:** the mechanism gate is passed for this setup. A small burst comparison is now technically reasonable, with frozen policies and a strict compute cap. Its outcome must compare full thinking, arrival-only budgeting, and live updates on the same trace. This proof has not launched that comparison or changed the existing quality requirement.

## Evidence and reproduction

- [Adapter and instructions](serving-proof/README.md)
- [Executed validation: all 18 checks](serving-proof/results/job-6309923/validation.json)
- [Reviewed token and answer summary](serving-proof/results/job-6309923/review-summary.json)
- [Runtime versions and source hashes](serving-proof/results/job-6309923/manifest.json)
- [Worker control events](serving-proof/results/job-6309923/worker.jsonl), [service events](serving-proof/results/job-6309923/service.jsonl), and [scheduler/KV trace](serving-proof/results/job-6309923/scheduler.jsonl)
- [A raw response](serving-proof/results/job-6309923/A.json), [B raw response](serving-proof/results/job-6309923/B.json), [C raw response](serving-proof/results/job-6309923/C.json)

The result directory also retains executed Python sources, the original launcher, actual scheduler allocation, complete dependency freeze, GPU identification, prompts, protocol, and server log. Local review verified every executed Python source against the manifest hashes. The current launcher defaults were subsequently tightened to the successful one-H100, 15-minute allocation; that resource-only launcher adjustment has not been rerun.
