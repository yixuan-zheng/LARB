# 6. Engineering gaps between this rig and a scaled rig

Each item is a place where a larger, faster experiment would either break something or quietly change
what is being measured. None of these are reasons not to scale; they are the work that scaling
implies.

## 6.1 The controller lives inside the engine

The current mechanism subclasses vLLM's scheduler to snapshot the queue at every step, registers a
logits processor that forces the cue and the terminal token for one request, and keeps per-request
state keyed by batch row, remapping it whenever vLLM swaps rows.

- **What breaks at scale:** row moves and per-row bookkeeping grow with concurrency; every engine
  upgrade is a potential silent break; and any change to batching order changes when cuts land.
- **What it affects:** whether the budget can be changed in flight at all, and whether the cue lands on
  the intended token.
- **Check first:** a CPU test that simulates many concurrent rows and random row swaps, plus one GPU
  gate that shows the cue starting at the exact budget for a request that is not row zero.

## 6.2 Graph capture versus per-step token forcing

Eager mode is currently on. CUDA graphs are where most of the throughput is.

- **What breaks:** graph capture assumes fixed execution paths; a logits processor that forces tokens
  for one row and not others may be incompatible, or may silently disable capture.
- **What it affects:** the achievable responses per GPU-hour, possibly by a large factor. It also
  affects timing comparability with every earlier result.
- **Check first:** run one frozen condition in both modes and compare (a) exact cue positions, (b)
  throughput, (c) token-level outputs on a matched seed. If outputs differ, the two modes are different
  experiments and must be reported separately.

## 6.3 Preemption, recompute and KV pressure

At two sequences the engine never preempts; the code even asserts it. At thirty-two it will.

- **What breaks:** a preempted request loses its place, may be recomputed, and its effective service
  time changes. A cut applied to a preempted request has different consequences than one applied to a
  running request.
- **What it affects:** latency distributions, the meaning of "waiting", and the fairness of comparing
  policies whose memory pressure differs (shorter budgets use less KV, so the adaptive policy may
  literally fit more requests).
- **Check first:** log preemption and recompute counts per policy, and report them next to the score.
  Treat "shorter budgets let more requests run" as a finding, not a nuisance.

## 6.4 Prefill, chunked batching and admission timing

`max_num_batched_tokens` is 2,048, so prefill and decode already interleave.

- **What breaks:** at high concurrency, the gap between HTTP admission and engine admission widens, and
  "arrival time" as observed by the client diverges from "start of service" as observed by the engine.
- **What it affects:** any claim about admission timing, queue delay, or time-to-first-token; and the
  deadline arithmetic if deadlines are measured from arrival.
- **Check first:** keep three timestamps per request (client arrival, HTTP accept, scheduler start) and
  report the distribution of each, not just the mean.

## 6.5 The answer phase and the cap

The 2,048-token answer allowance is currently a first-order cost: roughly a fifth to a third of
measured outcomes end as caps on AIME, and a cap is scored wrong.

- **What breaks when shortened:** more caps if the model needs the space, and a different accuracy
  profile per dataset. Shortening also changes what "correct" means in practice.
- **What it affects:** accuracy, latency, and the cap rate that the whole comparison depends on.
- **Check first:** measure the distribution of answer-phase tokens per dataset. If the 95th percentile
  is well under the proposed cap, shortening is nearly free; if not, it is a new experiment.

## 6.6 Timers, clocks and log volume

- Every request currently produces raw token IDs and a per-step scheduler snapshot. At a thousand
  requests of several thousand tokens each, logs move from megabytes to tens of gigabytes, and the
  per-step scheduler snapshots dominate.
- **What breaks:** full-fidelity reconstruction, which is what makes the audits possible; and storage
  quotas on the cluster.
- **What it affects:** the ability to re-derive results later, and the speed of analysis.
- **Check first:** decide what is sampled versus complete before the run (full tokens for all requests,
  scheduler snapshots at a fixed stride), and prove that the reduced record still reproduces the
  headline numbers.

## 6.7 Policy changes require draining the engine

Today a policy change is a service endpoint that refuses while any request is active. This is clean and
it costs GPU time: at high concurrency, draining between arms wastes minutes per switch, and it creates
a run-order effect (the first arm runs on a cold cache).

- **What breaks if policies are interleaved instead:** cross-request interference, because one policy's
  cuts change the queue that another policy's requests experience.
- **What it affects:** attribution. The current design already cannot claim per-request causality; an
  interleaved design must be analysed as a randomised experiment, not as paired cases.
- **Check first:** a small A/B/A test in one engine showing that the same policy scores the same before
  and after a switch.

## 6.8 Deadlines are a measurement instrument

The deadline is currently derived from a calibration run on the same hardware. That makes it
self-consistent but not meaningful, and it moves whenever throughput changes.

- **What breaks at scale:** faster service makes the same deadline trivially loose; the on-time metric
  then reports almost no misses and cannot distinguish policies.
- **What it affects:** the primary metric's sensitivity, and comparability between the old and new rig.
- **Check first:** choose deadlines as a multiple of the reference policy's median service time, then
  verify that 15-40% of reference-policy requests would miss. That range keeps the metric informative
  instead of saturated at one end.

## 6.9 The budget boundary is a contract, not a number

Several conventions are easy to break and expensive to break silently: whether the opening thinking
token counts, whether the cue's fourteen tokens count against the thinking budget, whether the answer
cap starts at the close token, and whether a naturally closed request can be cut.

- **What breaks:** a single miscount makes a new run incomparable with every stored result.
- **What it affects:** everything downstream, including the audit code that re-derives each cut's token
  position from the scheduler snapshot.
- **Check first:** keep the existing contracts in one module with tests, and re-run those tests against
  any engine change before measuring.

## 6.10 Throughput is a hypothesis, not a plan input

Our only measured rates are about 80 output tokens per second aggregate at two sequences, roughly 100
seconds for a single 8k-token response, and 25-110 measured responses per GPU-hour across past runs.
Nobody has measured what this engine does at sixteen or thirty-two sequences with eager mode on, let
alone with graphs.

- **What breaks:** any schedule built on assumed throughput.
- **What it affects:** the entire feasibility calculation for a big study.
- **Check first:** a short calibration that sweeps concurrency (1, 2, 4, 8, 16, 32) at a fixed
  generation length and reports tokens per second, per-request latency, KV occupancy and preemptions.
  Until that exists, every "we could do 1,000 responses per hour" statement is a guess.

## 6.11 Version pinning and the cost of improving the engine

The whole comparison set is tied to vLLM 0.11.2 and its internal APIs. Any upgrade for performance is
also a change of experiment.

- **What it affects:** comparability, and the credibility of "we improved the mechanism" versus "we
  upgraded the engine".
- **Check first:** decide explicitly whether the new rig is a continuation (same engine) or a new
  baseline (new engine plus a bridge experiment), and record it before measuring.

## 6.12 Bookkeeping that already exists and must not be lost

- A dataset exposure registry (the project has already consumed 124 of the 500-odd MATH indices and
  all 60 AIME 2024/2025 items).
- A frozen source lock per run, with executed hashes.
- A review queue for every wrong, ambiguous or capped answer, with raw text retained.
- CPU reproduction scripts that regenerate each published number from stored records.

At ten times the data volume, each of these becomes a small system rather than a habit. Deciding how
they scale is part of the plan, not an afterthought.
