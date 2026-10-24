# 6B: feasibility of a LASER-informed baseline

Prepared 2026-10-23. **Conditional go for baseline integration and a small development-only mechanics gate; not ready for a large 6C comparison.** The policy equations and confidence contract can be reproduced on CPU. Serving probes and exact rollback are the remaining engineering gate. Current LARB and the 5C results are unchanged. No GPU allocation, model generation, or dataset-question inspection was used in this investigation.

A fair comparison is feasible as an explicitly named **LASER-informed adaptation**, provided its replay, scheduling, and probe costs are visible. We cannot currently offer a faithful reproduction of the paper's complete system. The appropriate next decision is whether to implement and gate that adaptation, rather than allocate a full campaign now.

## What is specified, inherited, or adapted

The [LASER paper](https://arxiv.org/html/2606.31580v1), Algorithm 1 and Eqs. 5–8, supplies the load threshold and initial chunk-budget rules. Its serving evaluation uses discrete-event simulation. Its ATP/trial-answer description does not fully specify the probe prompt, confidence mask, tokenizer handling, or live branch implementation. No official LASER implementation was verified in the paper/title/repository searches. This is an access/reproduction gap, not proof that none exists.

[DEER](https://arxiv.org/html/2504.15895v3), §3, supplies a concrete linguistic ATP and geometric-confidence option. Its [official Qwen3 implementation](https://github.com/iie-ycx/DEER/blob/c9dd19fbffa27f841cfe47502d015b63811b4d1b/vllm-deer-qwen3.py) is pinned for inspection. Borrowing those details is explicit; LASER does not specify that exact program. [sources.json](sources.json) records primary URLs, revisions and hashes. Third-party model scripts are not vendored or imported.

| Component | Proposed reproducible contract | Qualification |
| --- | --- | --- |
| ATP | DEER(W), case-sensitive `Wait` stop string; detect during thinking only | No union with `Alternatively`, no entropy fallback; literal matching is not semantic reasoning detection |
| Probe | Branch from pre-ATP token checkpoint; append the exact inducer in `contract.json` | Preserve original token IDs for rollback; do not decode/re-tokenize the whole reasoning prefix |
| Probe sampling | Greedy, full vocabulary; return top-1 raw log probabilities | Declared choice; the inspected public Qwen3 probe call omits temperature, so its comment is not enough to establish greedy sampling |
| Confidence | Geometric mean of top-1 probabilities over generated probe positions; omit terminal EOS/think-close, retain other generated format tokens | Explicit scoring-mask adaptation; prompt tokens are excluded. Require complete, nonempty boxed output and aligned logprobs |
| Invalid probe | No confidence-triggered exit for empty, capped, malformed, missing or nonfinite evidence | It still consumes compute; budget/cap exhaustion can independently force finalization |
| Exit | Strict confidence greater than threshold; equality continues | Complete the transition and a separately generated final answer; a correct trial is not a scored final |
| Negative probe | Discard trial output and restore exact original prefix, including the ATP marker | New-call RNG state differs from uninterrupted inference; matching seeds cannot erase this limitation |
| Budget | Count ATP-delimited chunks using the paper allocator | No constant chunk-to-token conversion; a final allowed chunk still incurs its probe before budget finalization |
| Safety | Draft common thinking/answer/context caps plus bounded auxiliary decode | Safety caps take precedence. These match our serving envelope, rather than the paper's different total-length/think-ratio setup |

No answer references or correctness scores enter these decisions. Confidence measures model certainty, not calibrated correctness. LASER is not a consecutive-answer-consistency policy: importing Dynasor's stability window would create another method. Contradictory high-confidence probes remain possible.

The implementation in [reference.py](reference.py) covers policy math, confidence, parent/probe identity, immutable-prefix checks, cancellation, phase isolation, hard-cap and finalization state, and call accounting. It is **a CPU reference, not an integrated serving adapter**. Actual marker-to-token span mapping, boxed-output extraction and engine callback wiring remain gates; synthetic state transitions do not validate token transport.

## Two-slot load mismatch

The paper's target load is 10. For active count 0–2, starting its EMA at zero keeps the threshold at the **0.97 clamp**, and its load budget factor stays at 1. This is exact in the CPU check: the defaults would reduce to a strict confidence threshold plus prompt-length budgeting, rather than test useful overload adaptation here.

| Target | Steady active count 2: threshold | Chunk budget at prompt length 275 |
| --- | --- | --- |
| 10, paper default | 0.97000 | 15 |
| 2, capacity target | 0.95000 | 15 |
| 1, proposed capacity-scaled variant | 0.91954 | 7 |

Target 1 is a proposed adaptation chosen from the two-slot capacity, not a result-selected setting. It is not frozen for 6C. Target 2 permits threshold changes but never overload budget compression. Waiting count must not silently replace active count. Any queue-aware variant would have its own name and ablation.

The EMA is one global scalar per drained policy phase, reset to zero, with one serially ordered update per ATP evaluation. Auxiliary probes are excluded from parent active load. A live backend must establish how logical parent activity maps to actual engine activity during probing; this is particularly important under replay.

## Runtime compatibility and fair execution

CPU file inspection of the installed vLLM 0.11.2 matched five official tag files byte for byte: AsyncLLM, sampling parameters, sampler, and two logprob modules. [runtime-audit.json](runtime-audit.json) and [source-audit.json](source-audit.json) preserve that check. `generate`, `abort`, token-ID prompts and logprobs are available. The inspected AsyncLLM has no public per-request KV fork/pause/resume; engine-wide sleep is not a substitute.

The cached pinned tokenizer was checked on synthetic strings: standalone `Wait` is token 14190, think-close is 151668, and the probe inducer is seven tokens with no think-close token. [encoding-audit.json](encoding-audit.json) records the tokenizer file hashes. This does not validate marker spans in arbitrary streamed text.

The V1 sampler can return raw probabilities before temperature/penalties; record and verify this mode rather than assume it. Request `logprobs=1`, identify rank 1 explicitly, and check every scored position. Using the first dictionary value can pick the sampled token rather than the maximum. The pinned public DEER helper demonstrates that sensitivity on a synthetic window (0.20 versus top-1 0.98) and raises `ZeroDivisionError` on a one-token window. These are scoped compatibility observations from one unmodified AST function with a scalar math stub, not a full DEER/LASER evaluation. Our confidence reference handles those cases explicitly.

There are two possible backends:

- **Native checkpoint/fork/rollback:** closest to preserving a parent sequence, but requires new KV/scheduler engineering. Public prefix caching alone does not restore request state or RNG. This is beyond the bounded CPU session and is not implemented.
- **Serial stop/resubmit:** a practical prototype using public calls, exact token-ID prefixes and ordinary scheduling. It pays repeated prefill and changes re-entry order/RNG. Report it as an ATP replay adaptation; do not infer how a native branch implementation would perform from its latency.

All calls, including probes/finalization, would share the same engine and global two-sequence limit; no hidden extra GPU, parallel unlimited probes, or model call inside a logits processor. An aborted parent's resources must be released before child submission, without holding a permit the child needs. Cancellation must drain child work and charge any generated tail. New physical IDs retain phase/parent/probe identity.

The current adapter expects LARB metadata on every request and applies its own cue/cap logic. A new role-aware adapter/orchestrator is needed to distinguish parent, probe and final calls and exclude auxiliary sequences from policy load. LARB policy functions remain unchanged. Simply inserting probes into the existing endpoint is unsafe. An outer two-parent semaphore would also hide waiting pressure from LARB's scheduler snapshot; that is not an acceptable unnoticed fairness fix.

Before a large comparison, verify the proposed logical-load definition, queue re-entry and parent/child resource behavior under two busy slots. A replay/no-probe control should quantify wrapper effects. If those cannot be matched or bounded, the experiment can characterize the adaptation's cost, but cannot support a clean superiority claim against the prior algorithm.

## Accounting and CPU evidence

The draft envelope allows at most 15 probes × 64 decode tokens = **960 auxiliary decode tokens per parent**, in addition to original reasoning, cue and final answer. These are proposed safety limits, not evidence that 64 tokens suffices for a trial. Truncation stays visible and cannot silently trigger exit; calibration is restricted to exposed indices 0–99. Sparse ATPs still permit long reasoning until natural closure or the common token cap.

Per-call records separate submitted prompt length, actual computed prefill, cache hits, decode, discarded probe output, abort tail, queue time, and controller CPU time. Per-parent client latency runs from scheduled arrival to final terminal receipt, including every probe/replay/transition. Cache block occupancy, model allocation time and calibration costs also belong in the comparison. Missing executed-prefill/cache counters fail the cost-complete gate; submitted prefix lengths alone are insufficient. Tokens are reported by role rather than treated as interchangeable FLOPs. Parallel call durations must not be summed as wall latency.

Initially use cache-disabled diagnostics to expose replay costs. Any cache-enabled campaign reruns all arms with matched engine/cache settings and phase resets; old 5C values cannot serve as that campaign's control. The paper's small scalar policy cost does not make trial-answer model inference free.

**21 CPU tests pass**, including exact budget/threshold boundaries, empty/invalid confidence, long log-space windows, strict equality, immutable rollback, final-chunk charging, stale/foreign/cancelled probes, phase identity, answer failure, and duplicate/missing accounting rejection. [validation.json](validation.json) records a local synthetic policy-math microbenchmark; it excludes model, transport and tokenizer cost and is not a serving-overhead result. The synthetic accounting example charges all four calls and the discarded probe. No empirical probe cost or accuracy has been measured.

## What 6C would tell us, and what remains

A matched study could test whether LARB's simple queue-triggered intervention earns a favorable deadline/quality/compute tradeoff against confidence-driven load adaptation once probing costs are paid. It would not, by itself, demonstrate a novel scheduler or downstream-deadline forecasting: current LARB has neither that online deadline interface nor a forecasting model. The prior ACER algorithm-access gap also remains. Retaining LARB after 5C is justified; calling its existing load heuristic novel is not yet justified.

Suggested arms are unchanged admission/live LARB, the declared LASER adaptation, and fixed-threshold probes with identical prompt, sampling, masks, cadence, caps and costs. A fixed-threshold arm with the same allocator isolates adaptive thresholding; a standard fixed-threshold/no-allocator arm tests the whole added load policy. These are distinct controls. EDF, Dynasor's complete scheduler and queue-aware load variants stay separate.

Before allocating a full 6C campaign, the remaining work is:

1. Implement role-aware orchestration, token-aligned ATP/probe parsing, exact prefix rollback, and complete cost/event logging.
2. Establish load/queue/resource semantics, no deadlock/starvation, cancellation/drain, and cue/final completion in CPU integration tests.
3. With separate approval, run one bounded exposed-only GPU mechanics/cost gate. It should test two busy parents, positive/negative/capped probes and a no-probe wrapper control; it is not another accuracy campaign.
4. Calibrate only on 0–99, disclose failures and adaptation choices, then freeze a new matched workload, calibration budget, accuracy guard and resource ceiling for 6C. Do not tune on the consumed 24 validation questions; leave the other 376 provisionally unused until a new selection plan.

**Recommendation:** proceed with the small integration/gate route if the team accepts an explicitly adapted baseline. Do not launch a large 6C comparison from this CPU reference alone. If a faithful native branch is essential, budget that engineering separately or keep the contribution as the narrow LARB characterization established by 5C.
