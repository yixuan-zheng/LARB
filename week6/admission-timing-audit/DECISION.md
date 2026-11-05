# Week 6 decision: audit complete; review before implementation

## Finding and decision

The strongest observed explanation is **a correctness/coordination bottleneck, not failure to reuse completed request slots**. Live reduces mean queue delay 48.4% and reconstructed scheduled request-slot time 17.5% versus arrival-only. It rescues one previously late correct answer in each burst block. Correctness changes elsewhere cancel the primary gain. These are system-level paired observations, not causal labels for individual cuts.

Do not commit to a deadline-prediction hybrid now. The simple fixed-lane predictor found no single-cut rescue robust to the predeclared ±25% timing perturbation; two-block request-level median prediction errors are about 9–13s, with worst request-level median errors 76–83s. This rejects using this predictor as a reliable gate on current evidence, not all deadline-aware control or multi-cut opportunities.

## One selected, falsifiable hypothesis

**H1 — admission timing accounts for a material part of the apparent value of live intervention.** Rechecking an HTTP-assigned budget when a request actually enters the engine can retain a substantial fraction of live's burst efficiency/goodput benefit without interrupting established reasoning.

Evidence motivating H1: every measured burst run includes a long-budget request that was accepted when the HTTP snapshot showed no waiters, waited before actual engine entry, and was reduced at zero generated tokens. In the two latest blocks this request waited about 24s and 31s, respectively. Thus one counted live cut per burst is really a second admission-stage decision. One such request changes from correct to wrong in block 0. The repeatedly rescued downstream request is itself uncut. This is a recurrent structural mechanism and does not use question identity as a policy input.

H1 is not established. Fourteen of the latest sixteen cuts occur after some generation, and collective cuts can be necessary. The saved logs cannot tell whether entry-only reconsideration retains enough benefit. That is why the next proposal is an attribution experiment rather than an elaborate hybrid implementation.

## Minimal clean falsification experiment — proposal only

Three policies, all with the identical existing HTTP admission rule:

1. **HTTP arrival-only:** freeze the budget chosen by the current service snapshot; no later reduction.
2. **Engine-entry reconsideration:** at the request's first worker admission, reconsider the same 4K/8K pressure rule using the same-phase waiting snapshot, then freeze that budget for the rest of the request. No positive-progress reduction is permitted. The provisional HTTP budget and committed worker budget must be logged separately.
3. **Existing full live:** preserve both entry-time and subsequent running-request reductions.

The entry-only arm and full-live arm must use the same first-worker snapshot contract. No waiting request's budget is revised retroactively based on its eventual correctness, and no timer after first admission is silently classified as admission-only.

Use the existing 12-request burst/recovery recipe and both existing seed bases, with fresh engines per block and drained policy phases. That is **72 measured responses** (3 policies × 12 requests × 2 blocks). Predeclare rotated orders; two blocks do not fully counterbalance three policies or separate seed from run-time effects. Keep the original pinned H100 model/runtime, budgets, cue, final-answer allowance, arrivals, deadlines and grading. These are diagnostic development questions, not fresh validation. Fixed 4K/8K results remain context; this three-arm experiment cannot establish superiority over contemporaneous fixed baselines.

Before measurement, test (a) a long provisional budget reconsidered at first worker entry under real waiting, (b) already-running requests that retain their budget when waiting develops later, and (c) 8K recovery. A concrete envelope is up to seven engineering requests per block: two three-request scenarios plus one recovery request, **14 probes maximum**, for **86 total records**. The gate must verify the new branch and persistent no-live-cut property, not merely that a server starts. No correctness-based gate; capped outputs remain preserved failures.

Expected H100 duration from prior burst phases is roughly 2.5–3 hours plus startup/gates, not a guarantee. If this is approved and implemented, one six-hour allocation can retain the GPU across both blocks. A loose envelope of six burst phases with each last-arrival+1200s drain, two 20-minute gates and two 10-minute startups is about 5h02m before short preflight/analysis overhead. Freeze exact source, trace and timeout checks before any submission. No job is authorized by this document.

## Predeclared decision and stopping conditions

This is a mechanism pilot, not a formal noninferiority test.

- **Support H1 / earn fresh validation:** in each block, entry-only has no fewer correct-on-time answers than full live and retains at least half its positive token saving relative to HTTP arrival-only. Across both blocks it has no fewer overall correct answers than HTTP arrival-only, the quality reference; report the comparison with full live as well. The half-saving threshold gives “material” an explicit interpretation before new results. All metrics and unfavorable outcomes remain reported.
- **Reject this operational H1 or fail its correctness constraint; stop this branch:** the baseline contrast reproduces but entry-only fails any of those requirements. Do not tune a threshold, swap questions, retry a seed, or automatically build a more complicated controller.
- **Inconclusive, stop and review:** no qualifying engine-entry reconsideration occurs; full live has no positive efficiency contrast to reproduce; protocol/injection/gate coverage fails; or the required records are missing. Preserve all produced records, without automatic retry.

If the cheap entry-only controller succeeds, the next step would be a separately reviewed fresh evaluation with all relevant fixed baselines, enough independent traces/questions, and an application-justified correctness margin. If it fails, the result distinguishes a real in-flight contribution from late-admission coordination; it does not justify a predictor family sweep. Current CPU evidence does not support moving directly to a large GPU study.

## What is completed and what remains unapproved

Completed: reconstruction and integrity checks for 244 raw requests, 232 measured records, 12 probes, three engine runs; paired outcome accounting; release/slot reuse; cut timing; token-prefix/admission-path analysis; cross-block timing diagnostic; focused related-work comparison. No model inference, controller implementation, new Slurm job, package change or background monitor occurred during the audit. This public handoff packages those completed findings.

User review comes next: choose whether this minimal attribution experiment is worth implementing. Only then prepare reviewable source/protocol and separately decide GPU allocation.
