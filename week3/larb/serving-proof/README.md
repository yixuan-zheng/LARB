# Minimal live-budget vLLM adapter

This is a mechanism proof, not the burst policy experiment or a throughput benchmark. It serves real streaming HTTP requests through vLLM's asynchronous V1 engine, with a maximum of two active sequences and a third waiting request.

The engine stays unmodified. `live_budget.py` registers a batch logits processor through `AsyncEngineArgs.logits_processors`. `server.py` provides a loopback-only `/generate` stream and `/budget/{key}` control endpoint. The endpoint atomically replaces a JSON mailbox; the GPU worker reads changes at sampling boundaries. Stable request keys are carried in `SamplingParams.extra_args`. Per-request state follows vLLM's batch row moves.

Budget changes are irreversible reductions. A change below the current generated count starts the Stage 3 cue at the next sampling opportunity. The whole cue is emitted before ordinary answering resumes. Natural thinking closure makes subsequent budget updates inert. The existing 16,384-token thinking safety limit and 2,048-token post-close answer allowance remain; an answer-cap stop is recorded separately from natural EOS.

`AuditScheduler` subclasses the stock scheduler solely to record its output and KV allocation state. It delegates scheduling decisions unchanged. This tracing uses version-specific internal attributes; the adapter is pinned to vLLM 0.11.2 and is not claimed portable to other versions.

The three-request proof uses existing development problems 1, 0, and 2, fixed before GPU execution. These are engineering examples selected using the earlier completion records, not an accuracy sample: problem 1 previously continued to a completed answer after a 512-token cue. The initial draft used problem 18; checking saved data before execution showed that it previously exhausted its answer cap, so it was replaced before any GPU proof run. A begins first; B begins after A has produced 128 tokens; C is submitted after B produces 64 tokens. After A has produced at least 512 tokens, the client lowers A's thinking budget to 512. B is sent a budget of 1 after naturally closing its thinking block. This tests the control route directly; it does not implement or evaluate a queue-pressure policy.

## Checks

CPU tests cover a budget changed after generation starts, full cue completion, separate answer allowance, a naturally closed request, stale command versions, and row movement without cross-request contamination.

```bash
python -B -m unittest discover -s week3/larb/serving-proof -p test_control.py -v
```

The GPU proof records streaming outputs, service/worker/scheduler events, dependency versions, executed source hashes, and validation results. It requires actual A/B co-scheduling, C waiting and subsequently being co-scheduled, one admission per request, monotonic computed-token counts, retained KV block prefixes, zero preemptions, exact cue tokens, answer continuation, no forced answer-cap EOS, and a rejected late update on B. Cache evidence is scheduler allocation/computation evidence, not a bitwise comparison of cache tensors.

The file mailbox and per-step logging add overhead. Timing from this instrumented eager-mode service must not be compared with Stage 3 or presented as optimized serving performance.

## PACE execution

Use the isolated `~/scratch/CS6222-qwen3-baseline/vllm-proof-env` environment, leaving the original experiment environment unchanged. The job uses the cached pinned Qwen3-4B checkpoint offline. The current `run_proof.sbatch` requests one H100 for at most 15 minutes; its proof subprocess has a 12-minute timeout. There is no job array or automatic retry. These launcher defaults were tightened after the successful proof; its archived launcher and scheduler snapshot preserve the original submission and resource overrides.

```bash
cd ~/scratch/CS6222-qwen3-baseline
sbatch --output=serving-proof/results/slurm-%j.out serving-proof/run_proof.sbatch
```

`prove.py` starts and stops the service, waits for readiness, runs concurrent clients, and writes `validation.json`. Inspect that file and the raw evidence before calling the mechanism successful. A stopped or failed run is not a successful proof. Successful mechanism validation alone does not establish accuracy preservation or useful burst performance.

The completed proof is documented in [SERVING-PROOF-REPORT.md](../SERVING-PROOF-REPORT.md). Job 6309923 passed all 18 checks on one H100 in 233 allocation seconds. Its initial pending L40S reservation was moved to an H100 under the same account because the L40S nodes were occupied. No second allocation or inference retry was needed.

Pinned upstream interfaces: [processor contract](https://github.com/vllm-project/vllm/blob/v0.11.2/vllm/v1/sample/logits_processor/interface.py), [processor loading](https://github.com/vllm-project/vllm/blob/v0.11.2/vllm/v1/sample/logits_processor/__init__.py), [async engine](https://github.com/vllm-project/vllm/blob/v0.11.2/vllm/v1/engine/async_llm.py), and [stock scheduler](https://github.com/vllm-project/vllm/blob/v0.11.2/vllm/v1/core/sched/scheduler.py).
