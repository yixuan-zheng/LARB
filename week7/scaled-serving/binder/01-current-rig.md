# 1. The rig we have, and the assumptions baked into it

This describes the experimental machine as it exists today, in enough detail that a new planner
does not have to read weeks 3-6. Results are in [02-evidence.md](02-evidence.md); this file is
about design.

## 1.1 What the rig is

A real vLLM engine on one GPU, driven over HTTP by a replay client that sends the same questions at
scripted times. A thin control layer sits inside the engine and can do one thing that stock vLLM
cannot: **end a request's thinking phase early** and force it into its final answer. That single
capability is the whole research object. Everything else (batching, KV cache, sampling, streaming,
grading) is real engine behaviour, not simulated.

The control layer works by subclassing vLLM's scheduler to take a snapshot at every scheduling step,
and registering a logits processor that (a) can force the 14-token transition cue for an individual
request, (b) forces end-of-sequence when the answer allowance is exhausted, and (c) re-maps state
when vLLM moves a request between batch rows. The controller is therefore **inside** the engine, not
beside it. This matters for every scaling idea in [06-engineering-gaps.md](06-engineering-gaps.md).

## 1.2 Vocabulary used throughout these documents

| Term | Meaning here |
|---|---|
| Thinking budget | Maximum number of generated reasoning tokens before the cue is forced. Not a total generation limit. |
| Cut | An irreversible decision to stop a running request's thinking at its current token count and force the cue. |
| Cue | A fixed 14-token text plus `</think>` that moves the model into answer mode. Counted as tokens but not as thinking. |
| Answer allowance | Separate 2,048-token cap after the cue. Hitting it is a failure, not a truncated success. |
| Correct on time | Correct final answer, normal completion, received before the request's deadline. The primary metric. |
| Horizon | The observation window for a load phase: last scheduled arrival plus the deadline. |
| Phase | One policy running over one frozen arrival trace; the engine is drained between phases. |
| Cap | A request that ran out of thinking budget or answer allowance. Counted as wrong. |

## 1.3 Fixed settings

| Item | Value | Where it matters |
|---|---|---|
| Model | `Qwen/Qwen3-4B`, revision `1cfa9a7…`, BF16 | 4B parameters, ~24k context. Small by serving-research standards. |
| Engine | vLLM 0.11.2, torch 2.9.0, transformers 4.57.6 | Pinned. The controller imports engine internals, so upgrades are not free. |
| Concurrency | `max_num_seqs = 2`, `max_num_batched_tokens = 2048` | Two requests can run at once. "A request is waiting" therefore means the machine is full. |
| Execution | `enforce_eager = True`, prefix caching off | Removes CUDA-graph capture. Costs a large fraction of achievable decode throughput. |
| Context / memory | `max_model_len = 24576`, GPU memory utilisation 0.8 | Sized for prompt + 16k thinking + 2k answer. |
| Sampling | temperature 0.6, top_p 0.95, top_k 20, per-request seed | Each request's seed is `base + question id`, so seeds are matched across policies but never produce matched trajectories. |
| Prompt | Question text + "Please put your final answer within `\boxed{}`.", thinking enabled | Answers are single integers, graded by extraction plus Math-Verify. |
| Thinking budgets used | 2,048 / 4,096 / 8,192 / 16,384 | Different weeks used different pairs. The serving work settled on 4k/8k. |
| Deadline | 1.5 x the slowest of four paired 8k calibration requests (about 236 s in weeks 5-6); earlier weeks used twice the slowest calibration request (95-125 s) | Derived from a measurement, not from an application requirement. |
| Hardware | 1 x H100 80GB, 8 CPUs, 64 GB RAM; some earlier work used L40S | Slurm allocations capped at 3-6 hours. |

## 1.4 Lifecycle of one request

1. **Scheduled arrival.** The replay client wakes at a pre-computed offset on its own clock.
2. **HTTP admission.** The service reads the current queue snapshot and chooses a provisional budget:
   8k if nothing is waiting, 4k if something is. A request can sit here for tens of seconds.
3. **Engine admission.** The scheduler actually starts the request, possibly much later than step 2.
4. **Generation.** Sampling proceeds normally. The controller re-reads the queue at scheduling steps.
5. **Cut (live policies only).** If the rule fires and the request is still thinking, its budget drops
   (usually to 4,096). One-way; it can never be raised again.
6. **Cue.** At the budget boundary the 14-token cue is forced, and the model switches to answering.
7. **Answer phase.** Up to 2,048 tokens; forced end-of-sequence at the cap.
8. **Grading.** Boxed integer extraction, Math-Verify comparison, cap and completion flags preserved.

The gap between steps 2 and 3 is the reason the engine-entry hypothesis existed: a budget chosen when
the queue was empty was sometimes reduced before one token had been generated.

## 1.5 The policies that exist

| Policy | At admission | While running | Introduced |
|---|---|---|---|
| `fixed4k` | 4,096, always | never changes | week 3 |
| `fixed8k` | 8,192, always | never changes | week 3 |
| `full` / `fixed16k` | 16,384 (safety limit) | never changes | weeks 3-5 |
| `live` | 8k if no waiter, 4k if one waiter | one irreversible cut to 4k when a waiter appears | week 3 |
| `live_one` | same rule, threshold of one waiter | same, lower threshold | week 5 |
| `arrival` | 8k/4k from the queue snapshot, then frozen | never changes | week 6 |
| `entry` | provisional budget from HTTP, re-decided once at engine admission, then frozen | never changes | week 6 |

All of them share the same cue, answer allowance, deadline recipe and grading. That is what makes the
comparisons arithmetic rather than rhetorical.

## 1.6 Workload recipes

Arrivals are scripted from a single scale number `T`, the slowest of four paired 8k calibration
requests. Typical (weeks 5-6):

- **Low:** 4 requests, 1.25 T apart.
- **Near:** 8 requests, 0.4 T apart.
- **Burst/recovery:** 2 at time 0, 6 more at 0.5 T spaced 0.05 s apart, then 4 recovery requests at
  4 T, 5.25 T, 6.5 T, 7.75 T.

Policy order rotates between conditions, but there is **one trace per condition and one repetition**.
The engine is drained and restarted between policies, so a policy comparison is also a run-order
comparison.

## 1.7 Datasets and grading

| Weeks | Pool | Size used | Notes |
|---|---|---|---|
| 3-5 (builder) | MATH-500, first 100 indices | 100 questions, hash-selected slices of 6-24 | Answers are short; model is at ~95% with full thinking |
| 5-6 (serving) | AIME 2025 | 30 questions, 12 used per trace, 2 seeds | Hard; accuracy 30-52% depending on budget |
| 6 (prefix study) | AIME 2024 | 30 questions, 2 seeds | Deliberately a fresh cohort for the project, still likely in pretraining data |

Grading is exact-integer after boxed-answer extraction. Later work used Math-Verify 0.9.0, which
recovers some equivalent forms. Six manual extraction corrections were made once, under hashes, in
week 3. Caps are failures; there is no partial credit; and a wrong answer that looked confidently
formatted is still wrong.

## 1.8 How much data each run produced

| Study | Measured responses | Hardware | Wall time / GPU time | Responses per GPU-hour |
|---|---:|---|---|---:|
| week 3 burst pilot | 36 (+2 calibration) | 1 H100 | one allocation | not recorded |
| week 3 budget sweep | 600 | up to 6 L40S, sequential per worker | several hours | not recorded |
| week 4 development comparison | 96 | 1 H100 | 58 min | ~99 |
| week 4 held-out campaign | 288 | 6 x 1 H100 | 5.14 GPU-h | ~56 |
| week 4 fixed-budget controls | 192 | 1 H100 | 1.74 GPU-h | ~110 |
| week 5 one-waiter | 141 | 2 allocations (3 h and 4 h caps) | partly used | not recorded |
| week 5 queue-pressure pilot | 72 (+4 probes) | 1 H100 | 2 h 21 min | ~31 |
| week 6 arrival ablation | 160 (+8 probes) | 1 H100 | 4 h 39 min | ~34 |
| week 6 engine-entry | 72 (+14 probes) | 1 H100 | 2 h 50 min | ~25 |
| week 6 prefix study | 60 instances / 183 calls | 1 L40S | 2 h 35 min | ~71 calls |

The range is wide because the workload differs: week 4 used a shorter deadline and a smaller long
budget, week 6 used 8k thinking plus long AIME answers. The honest summary is **25-110 measured
responses per GPU-hour, typically 30-60 for the AIME workloads we care about.**

Two consequences. First, every conclusion so far rests on tens of answers, not hundreds. Second, the
cost is dominated by long single-sequence generation: an 8k-token response takes about 100 seconds,
and aggregate throughput at two sequences is roughly 80 output tokens per second. A 1,000-response
experiment at today's throughput is a 12- rather than a 1-2-hour job.

## 1.9 The assumption ledger

Each row is a choice that was reasonable when made, is now load-bearing, and constrains what any new
result can mean.

| Assumption | Why it was chosen | What it costs us | What changes if relaxed |
|---|---|---|---|
| Answer allowance of 2,048 tokens | Early MATH-500 answers were short; the cap guarded against runaway answers | On AIME it binds hard: 47 of 160 measured responses (29%) in the last big run were caps, and every one counts as wrong. It also makes the answer phase a large share of service time, diluting the effect of thinking budgets. | Shorter answers make requests much cheaper and raise throughput, but cap failures move the measured accuracy in ways that must be checked per dataset. |
| Two concurrent requests | With two slots, one waiting request already means the machine is full, which makes pressure experiments cheap and mechanically checkable | The queue never exceeds a handful of requests; "pressure" is binary; the controller's threshold is a property of the rig, not of load; no batching effects, no preemption, no KV pressure. | Real queueing statistics appear, thresholds must be redefined, preemption and recompute enter the picture, and cuts compete with scheduling rather than being the only lever. |
| 4-billion-parameter model | Fits one GPU, fast to iterate | Budget sensitivity, overthinking behaviour and answer verbosity may all be size-dependent; 4B may be the least interesting regime for reasoning control. | Bigger models are slower per token and need more context; conclusions may or may not transfer, so any change of size needs an explicit bridge experiment. |
| Eager execution | Simplifies per-step logits manipulation and row bookkeeping; predictable timing | Leaves a large factor of decode throughput unused, so wall-clock cost per data point is inflated. | Enabling graph capture probably multiplies throughput; it requires proving that per-request forcing still works and is measured honestly. |
| Prefix caching off | Keeps accounting simple and avoids cache-state confounds | Unrealistic for production and wasteful when the same questions repeat across policies and seeds. | Repeated-question designs become much cheaper; cache hits change prefill cost and must be reported. |
| Cue-based stopping | Gives a clean, comparable boundary between thinking and answering | The 14 forced tokens and the answer phase are fixed overheads attached to every cut; a cut is not an instant finish (typically 14-90 s remain). | Any stopping mechanism that is not the cue needs its own fairness and accounting. |
| Pressure = non-empty queue | Simple, observable, pre-declared | At two slots it is a rig artefact; at high concurrency it fires constantly. | Needs a threshold expressed as a fraction of capacity, or a deadline-aware trigger. |
| Deadline from calibration | Cheap and independent of outcomes | It is generous in weeks 5-6 (~236 s against a 140-200 s mean latency), so the on-time metric has little room to move; in week 4 (~95-125 s) it was tight and produced bigger differences. | Exogenous service-level objectives make the metric sensitive and comparable across rigs, but must be justified by an application story. |
| 12-30 questions, one trace, 1-2 seeds | Fits the GPU budget | Everything is a case study; a 2-3 answer difference is inside the noise. | Larger pools plus many seeds per question, analysed as paired within-question differences. |
| Caps and wrong answers stay in the denominator | Honest scoring | Correct but occasionally harsh when the cap is the binding constraint | Keep it. Changing it now would make new results incomparable with old ones. |
| No utilisation or KV instrumentation | Not needed for the mechanism question | Cannot say whether the GPU was busy, memory-bound or idle; cannot claim efficiency | Directly answers the "are we saturating the device" question the next plan depends on. |
| Engine-level patching | It is the only way to change a budget in flight in this vLLM version | Ties every result to one engine build and one internal API; scaling multiplies the surface area for bugs | A supported interface (or a smaller engine fork) would make scale-up and reproduction far easier. |

## 1.10 What the rig does well, and should keep

- It executes real batching and real KV-cache management; it is not a simulator.
- It changes a budget **without** replaying the prefix or re-tokenising, so a cut costs nothing extra.
- It preserves every failure: caps, timeouts, errors and missing outputs have always stayed in the record.
- It freezes sources, traces and hashes before measurement, and separates the analysis code from the
  serving code, so results can be re-derived months later.
- It reports per-question paired outcomes, not just aggregates, which is why the quality flips in the
  most recent runs were visible at all.

Those properties are worth more than any single result, and a scaled rig should not lose them.
