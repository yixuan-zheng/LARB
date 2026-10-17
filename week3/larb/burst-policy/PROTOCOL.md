# Controlled burst-policy pilot

Frozen before GPU execution. Machine-readable settings are in `spec.json`.

## Question

During one small burst, does updating active requests' thinking budgets yield more correct answers before a fixed deadline than full thinking and budgets chosen only at arrival?

## Fixed setup

Use the proven vLLM 0.11.2 environment, cached pinned Qwen3-4B checkpoint, BF16, one H100, two active sequences, and unchanged stock batching decisions. Preserve Stage 3 sampling settings, per-problem seeds, cue, thinking safety limit, and answer allowance. Full thinking stops as a failure at the thinking safety limit; it does not receive a finalization cue there.

Use development indices 0–11 in their original order, without filtering by correctness. Run one response per problem per policy: 36 measured attempts. Use two additional calibration requests, indices 0 and 2. No GPU array, repeated seeds, model changes, budget sweep, automatic retries, or post-outcome tuning. One allocation has a 60-minute ceiling and a 55-minute process timeout. Reuse one engine, fully draining each phase before the next.

## Policies

- **Full:** keep thinking until natural closure or the safety limit.
- **Arrival:** if the latest observed engine queue contains at least two waiting requests when a request arrives, assign 2,048 thinking tokens; otherwise assign the full allowance. Never change it afterward.
- **Live:** use the same arrival rule, and additionally reduce active thinking requests to 2,048 tokens when the observed waiting queue has at least two requests. Never increase a budget or cut a request already answering. A request already past the new limit transitions at the next sampling opportunity.

The stock scheduler publishes an atomic queue snapshot every engine step after scheduling. The service uses the latest snapshot at arrival; the GPU worker uses it for live changes. The run records queue IDs, snapshot steps, ages, and decisions. This is an observed queue signal with propagation delay, not a claim of instantaneous global state. Queue snapshots are scoped to the current phase. All policies run through the same control and tracing code.

The seeded order, fixed before execution, is **arrival, live, full** (shuffle seed 622204). One order and one trace do not remove order effects. Two calibration requests warm the engine before measurement. Prefix caching is disabled throughout. HTTP streaming sends delta metadata rather than re-serializing the entire growing output on every token.

## Freeze the trace before measuring policies

Run calibration indices 0 and 2 concurrently with full thinking. Let their measured completion latencies, from scheduled arrival, be T0 and T2.

- Burst begins at `0.25 × min(T0,T2)` seconds.
- Every request has relative completion deadline `2 × max(T0,T2)` seconds.
- Indices 0 and 1 arrive at time zero.
- Indices 2–11 arrive at the burst time, spaced 0.05 seconds apart.

Write and hash `trace.json` before starting the first measured policy. Reuse its exact arrivals and deadline for all three policies. Do not revise it after seeing their outputs. Calibration inputs are selected engineering examples; this is not a representative workload claim.

## Measurement and grading

Primary outcome: number of correct, normally completed answers within their frozen relative deadlines. Report count divided by a common observation horizon (last scheduled arrival plus relative deadline) as deadline goodput. This keeps the primary denominator the same across policies.

Also report completed correctness out of 12; queue delay from actual server receipt to worker admission; completion latency from scheduled arrival; client injection lag; drain time from trace start; natural and cap terminations; arrival budgets; actual live reductions and cue starts. Requests are drained even if late. Safety-cap and answer-cap terminations count as failures, including when forced EOS makes vLLM's native finish label say `stop`.

Grade boxed final answers with the existing canonical normalization and math-verify 0.9.0. Review extraction/parser ambiguities without changing generation. Preserve raw outputs, caps, source hashes, dependency versions, queue events, and sampled cache-allocation evidence. Do not substitute the earlier Transformers timings or answers for a serving baseline.

## Decision rule

A provisional reason to continue requires all three: a genuine change to an already-generating request; more correct on-time completions than both baselines; and no fewer completed-correct answers than full thinking on this trace.

Otherwise report negative or inconclusive findings and stop this pilot without tuning. One error is 8.3 percentage points: this experiment cannot establish the earlier three-percentage-point quality tolerance. Instrumentation, eager execution, a single development trace, and one sampled response per problem limit any performance or quality claim, even if the pilot screen passes.
