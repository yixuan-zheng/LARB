# Bounded serving feasibility check

**Update after implementation:** the minimal adapter passes a real concurrent-serving proof; see [SERVING-PROOF-REPORT.md](SERVING-PROOF-REPORT.md). The subsequent [bounded burst pilot](BURST-POLICY-REPORT.md) also passed its preliminary screen on one development trace. The original assessment below records what was unverified at the earlier check. The core mechanism gap is resolved; a general quality guarantee and an isolated mid-generation advantage over admission-only control remain unestablished.

## Decision: burst experiment gate not passed

The token cutoff is straightforward. Integrating it into a useful concurrent serving experiment is not yet demonstrated to be straightforward in the available code. Do not allocate a burst experiment yet. This is an engineering readiness decision, not a rejection of Russ's hypothesis.

Scope: inspect existing code, check the existing PACE environment read-only, examine official engine documentation, and exercise the existing budget state on CPU. No installation, GPU allocation, inference, remote modification, or engine fork was performed.

## What is already available?

`code/stage3_sweep.py` runs one Transformers `generate()` call at a time. Its logits processor can force the existing finalization cue without restarting the response. The budget state is per request. The CPU check confirms that lowering a budget below an already-generated count triggers forcing on the next control check, leaves another request unaffected, and does not end the answer when the thinking block closes. It also checks that an existing cache reference need not change at the state-control level. This is not a model-level cache or serving validation.

The earlier `week2/workstream-c/code/gpu_replay.py` can interleave retained-cache cohorts, but keeps a padded cohort until all its members finish. It does not demonstrate immediate reuse of each completed request's slot in a continuous batch. Porting that harness could test its own queueing behavior, but could make the apparent benefit depend on cohort stragglers. It is not a substitute for the serving comparison we want.

A read-only search under the existing PACE environment's `gemma3n/lib` directory (maximum depth three) found no vLLM package path. This is a scoped environment check, not an inventory of every environment on PACE. The account's queue was empty at the check. The previously used environment remains unchanged.

## Plausible integration route and unresolved work

Use a pinned vLLM version in a separate environment, one GPU, one worker, no speculative decoding. Retain one request and its KV cache throughout generation. A worker-side logits processor would apply the same forced cue used in Stage 3. An engine-side pressure signal would reduce selected active requests' budgets before a subsequent sampling step. Existing answering requests would not be cut again.

Official vLLM documentation describes batch-level logits processors and request additions, removals, and moves. Its current thinking-budget implementation initializes per-request budget state when a request is added. Those are useful building blocks; they do not by themselves establish a supported way to update an active request's budget from queue pressure. Simply changing the client-side sampling object after submission is not a verified control channel.

Sources inspected:

- [Logits processor design](https://docs.vllm.ai/en/stable/design/logits_processors/): batch state handling and sampler hooks.
- [Thinking-budget state implementation](https://docs.vllm.ai/en/stable/api/vllm/v1/sample/thinking_budget_state/): request budget initialization and token forcing.

These are moving documentation references, not a pinned or installed implementation. Any subsequent integration must record the exact version and runner configuration. Native thinking-budget support may use a different transition from our cue; changing that transition would confound the serving comparison.

Remaining obligations:

1. Install and load the pinned model in an isolated compatible serving environment without altering the existing experiment environment.
2. Connect real waiting-queue pressure to stable request identities in the worker. Avoid relying on transient batch row numbers or an unsynchronized global variable across processes.
3. Handle request movement, cancellation, natural thinking completion, and completion-slot reuse correctly.
4. Enforce the existing thinking safety cap and a separate post-close answer cap. A total output limit alone is not equivalent.
5. Log budget changes, cue tokens, request admission/completion, and evidence that no abort-and-resubmit or prefix replay occurred.

No working adapter currently satisfies these obligations. A custom continuous-batching scheduler or invasive engine changes would exceed a straightforward preliminary integration.

## Gate for a later small burst experiment

The implementation gate requires a small adapter using documented extension points, no engine fork, no custom batching scheduler, and the same transition and caps for all compared policies. Before a burst run, a tiny model smoke check must show:

- Two overlapping requests; pressure introduced after one has begun thinking changes that active request's budget.
- That request closes thinking, continues its answer, and finishes with the same request identity and retained cache; no cancellation/replay.
- A naturally closed request is unaffected, request state remains correct after batch movement, and a queued request is admitted when a slot is released.

CPU state checks pass, but these integration/model checks have not run. A CPU mock must not be represented as satisfying them. The user's conditional authorization therefore has not been activated by this check.

## Concrete cap if the gate is later passed

This is a proposed ceiling, not a submitted job or an approved runtime expansion:

- One L40S allocation, maximum 60 minutes including loading, warmup, and smoke checks. No array, retries, or automatic extension. Stop at the cap and report incomplete results if necessary.
- Same pinned Qwen3-4B checkpoint, sampling settings, finalization cue, and output caps as Stage 3. Rerun every baseline in the serving engine; do not substitute old Transformers timings or answers.
- First 12 development problem indices in fixed order, selected without correctness filtering. Three policies on the same single arrival trace: full thinking; pressure-based budget chosen only at arrival; pressure-based budget also updated on active requests. At most 36 measured attempts plus four smoke/calibration requests. No budget sweep or model change.
- Maximum two active requests. Before measuring policies, freeze one trace with an initial pair followed by a queue-building burst. Use at most four smoke/calibration requests to choose and record arrival spacing and one relative completion deadline; no tuning after policy outcomes are seen.
- One predeclared rule for both adaptive policies: if at least two requests are waiting, reduce the permitted thinking count to 2,048. Arrival-only applies it once when each request arrives; dynamic applies the same rule additionally to active thinking requests at sampling boundaries. Requests already beyond that count transition at the next opportunity. Keep decisions irreversible. Record pressure at arrival separately from admission; there is no answer-aware selection.
- Report actual intervention count, completed-correct answers, correct completions by the frozen deadline, queue delay, answer completion latency, and drain time. Show whether capacity is actually reused after interrupted requests finish.

With 12 problems, one error is 8.3 percentage points: this pilot cannot establish the original three-point quality tolerance. A provisional reason to continue would require a real mid-request intervention, more correct on-time completions than both baselines, and no additional observed correctness loss versus full thinking. This is a diagnostic screen on one tiny trace, not a statistical claim or permission for a larger run. A negative or inconclusive result does not trigger automatic tuning.

## Evidence

[CPU checks](feasibility/cpu-check.json) record the state-only assertions. Existing Stage 2/3 reports provide model evidence for fixed in-place cutoffs; they do not validate concurrent service or dynamic worker control. No burst results exist from this check.
