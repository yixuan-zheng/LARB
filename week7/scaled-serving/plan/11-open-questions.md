# 11. Decisions requiring sign-off

The plan has defaults for every item below. A default is not a decision until the owner records it
in `PROTOCOL.md`. The items are ordered by how much they change the experiment.

## 11.1 The declared SLO: 180 s or 240 s

**Recommended default:** 180 s from client arrival, calibrated to 20-30% misses for `fixed8k`.

Why it matters: the deadline is the measurement instrument (binder 6.8). At 180 s and 32 slots, the
queue simulation puts the reference arm in the 15-40% band at a plausible load. At 240 s the band is
still reachable but needs a higher arrival rate, which means more queueing and more cuts. A
too-loose deadline makes the on-time metric decorative; a too-tight one makes almost everything
late and hides accuracy.

Alternatives: 240 s if the calibration cannot reach the band at 180 s without overloading; a
two-class SLO only as an extension.

## 11.2 The answer contract: legacy or short-boxed

**Recommended default:** run the 384-response bridge; adopt `short_boxed` only if it is within 2
points of legacy, lowers the cap rate, and reduces the median answer phase below 256 tokens. Use
legacy otherwise.

Why it matters: the legacy answer phase has a median of 1,371 tokens and 22-33% caps on the AIME
work. Shortening it is the single largest throughput lever, but it changes what "correct" means and
must be bridged against the stored results.

Alternatives: legacy for the whole main run (safest continuity, 15-20% more tokens); short contract
for the whole main run only after the bridge passes (recommended if the bridge is clean).

## 11.3 Signal cohort size: 200, 246, or 500+

**Recommended default:** 220-246 signal questions, all four arms, 4 seeds, two pressure conditions
and a short low-load control. This is the realism-first main path. It is powered for about 5-6
points at ICC 0.2-0.4; a 5-point effect is at the edge.

Why it matters: the 3-point clause needs 500-800 questions at the observed ICC. A 220-question
cohort cannot resolve it, and the report must say so. A larger cohort is a second job, not a
free addition.

Alternatives: 246 questions if QC leaves that many; 500+ only as the resolution extension if the
main result is in the 2-5 point ambiguous band.

## 11.4 Seeds per question: 4 or 6

**Recommended default:** 4 seeds for the main run. Do not add seeds to rescue power; if throughput
is exceptional (roughly 2,000 output tokens/s), a 6-seed extension is possible only after the main
path.

Why it matters: seeds add responses but not independent questions. At ICC 0.2-0.4, 220 questions x
4 seeds already give about 400-550 effective pairs; 6 seeds add less than the raw count suggests.
At the 12-question ICC 0.6 upper bound, even 6 seeds leave the MDE near 7 points. Throughput and
question count are the binding constraints, not seed count.

## 11.5 Cut rule: cascade or legacy all-at-once

**Recommended default:** cascade, one eligible request per scheduler step, largest remaining budget
first, progress window 512 to budget-1,024. Keep `live_all` as a calibration/extension arm.

Why it matters: at two slots, cutting every eligible request at once was the only meaningful
version of the policy. At 32 slots it can cut dozens of requests in response to one burst, which is
neither realistic nor a fair test of a selective mechanism. The cascade is a new policy and needs
its own manipulation check.

Alternatives: `live_all` for strict continuity with weeks 3-6; a progress-window or deadline-aware
variant in an extension.

## 11.6 Filler traffic: 30%, 20%, or none

**Recommended default:** 30% filler, fixed 1,024-token budget, never scored.

Why it matters: filler creates a realistic service-time distribution and keeps the batch full. It
also consumes capacity that would otherwise serve signal requests, so the arrival rate must be
calibrated with the mix. The quality endpoint is signal-only.

Alternatives: 20% if the low-load control is too noisy; 0% only if the signal pool itself has a
wide enough service-time distribution.

## 11.7 Pressure threshold and persistence

**Recommended default:** `threshold = max(4, ceil(0.25 * max_num_seqs))` (8 at 32 slots),
`persistence = 2` scheduler steps. Freeze after Gate F.

Why it matters: "one request waiting" is meaningless at 32 slots. The threshold must be a fraction
of capacity, and the persistence rule prevents a momentary gap from permanently shortening a
request. The calibration records the pressure fraction in each condition; a threshold that never
fires or always fires is rejected.

Alternatives: waiting >= 4 (12.5%) if 8 is too rare; a wait-time trigger (oldest waiter > 20 s) if
the count is noisy. Both are calibration-only choices.

## 11.8 Prefix caching and CUDA graphs

**Recommended default:** prefix caching off; CUDA graphs on only after Gate B passes.

Why it matters: graphs recover throughput; cache reuse across arms creates a run-order benefit and
changes prefill cost. The main path prefers a clean comparison to a faster but confounded one.

Alternatives: prefix caching on with a filler warm-up and prefill cost reported separately, as a
throughput extension.

## 11.9 Hardware envelope and replication

**Recommended default:** one H100, one 16 h gate job, one 16 h main job. A second block is a
separate allocation.

Why it matters: the main comparison should run on one GPU to avoid hardware heterogeneity. Multiple
GPUs are useful for replication, not for splitting arms.

Alternatives: 2-3 H100s in parallel for the resolution extension; each arm still runs on one GPU
and the analysis includes GPU id.

## 11.10 Model size bridge

**Recommended default:** Qwen3-4B for the main path; Qwen3-8B only as an extension if the 4B result
is positive.

Why it matters: the binder warns that budget sensitivity and overthinking may be size-dependent.
A 4B result is not a general claim about reasoning serving. The bridge is a separate experiment
with its own calibration and its own throughput cost.

## 11.11 Primary MDE and the 3-point clause

**Recommended default:** pre-register a 5-6 point MDE for H1/H2 (5 is at the edge; the realised
ICC decides); report H3 as a CI, not a non-inferiority claim, unless the upper bound is below the
agreed margin (5 points interim, 3 points only with the resolution extension).

Why it matters: the main cohort cannot resolve 3 points. Promising it would repeat the project's
worst habit: claiming a small accuracy preservation from tens of answers.

## 11.12 Decision record

For each item, record in `PROTOCOL.md`:

```
item:
choice:
date:
owner:
rationale:
```

An item left blank is not a default; it is an open decision that blocks the main run.

