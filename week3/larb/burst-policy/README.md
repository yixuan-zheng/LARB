# Controlled burst-policy comparison

Completed result: [BURST-POLICY-REPORT.md](../BURST-POLICY-REPORT.md). Job 6320907 passed the frozen preliminary screen: 6 correct on-time answers with live updates, versus 4 full and 3 arrival-only, with 11/12 aggregate completed correctness for both live and full. One H100 allocation lasted 21:04. This does not isolate live intervention from admission-time adaptation or establish the three-point quality floor.

Read [PROTOCOL.md](PROTOCOL.md) and `spec.json` for the settings frozen before execution. This pilot follows the successful live-budget serving proof. It compares full thinking, budgets selected at arrival, and additional updates to active requests under queue pressure.

The pilot uses one H100, one vLLM engine with two active slots, the first 12 development problems, two calibration requests, and 36 measured attempts. The launcher has a one-hour allocation ceiling and a 55-minute process timeout. It does not retry, extend, sweep parameters, or submit a job array.

`server.py` pretokenizes the fixed prompts and serves delta streams. `adapter.py` observes the stock vLLM scheduler, publishes phase-scoped queue snapshots, and applies logits-only interventions. `policy.py` contains the small decision rule. They reuse the unchanged `serving-proof/control.py` request state, whose executed copy and hash are retained with the run. The audit subclass reads private vLLM 0.11.2 scheduler attributes; this is a pinned preliminary harness, not a portable production extension.

`run.py` calibrates once, writes and hashes the trace before measuring policies, runs the seeded fixed order, and fully drains each phase. Both adaptive policies see the same kind of observed queue signal. Arrival-only decides at actual HTTP arrival, not when the request is admitted. Live additionally changes active thinking requests. Snapshot ages and queue identities are recorded.

The full-thinking safety limit stops the response without adding a finalization cue. Cap-induced EOS is explicitly logged, so vLLM's native `stop` finish label cannot turn a cap failure into a normal completion for grading.

## Execution on PACE

Use the existing isolated `vllm-proof-env` and cached pinned Qwen3-4B checkpoint. The original Transformers experiment environment is unchanged.

```bash
cd ~/scratch/CS6222-qwen3-baseline
sbatch --output=burst-policy/results/slurm-%j.out burst-policy/run_burst.sbatch
```

Artifacts live in `burst-policy/results/job-JOB_ID/`: executed sources and hashes, runtime versions, frozen specification and derived trace, raw responses, client injection/completion records, worker decisions, queue events, sampled KV block allocations, and server diagnostics. `run-complete.json` is written only after all 38 attempts drain.

## Local CPU analysis

Use the same math-verify 0.9.0 grading environment as Stage 3; `stage3/requirements-analysis.txt` pins the analysis dependencies. From the repository root:

```bash
PYTHONPATH=/tmp/qwen-stage3-grading-deps MPLCONFIGDIR=/tmp/qwen-stage3-mpl \
  /Users/shuyizhang/anaconda3/bin/python -B \
  week3/larb/code/analyze_burst.py \
  --root week3/larb/burst-policy/results/job-JOB_ID
```

Analysis requires the complete run. It audits source hashes, identical frozen arrivals, pressure decisions against scheduler snapshots, cue tokens, cap boundaries, no reopened thinking, monotonic computed-token counts, retained sampled KV prefixes, and zero preemptions. It grades final boxed answers using the existing canonical and mathematical equivalence functions, with any extraction ambiguity recorded for review. It produces per-request results, summary metrics, a review queue, source/dependency metadata, a pre-cutoff prefix diagnostic, and a static queue/execution timeline.

Primary completion uses the server's final-output-ready timestamp relative to the scheduled arrival, matching the calibration implementation. Client-received completion is also recorded and checked for deadline-count differences. Queue time starts at actual server receipt, while injection lag is reported separately. Deadline goodput uses one fixed observation horizon for all policies; drain time is a separate diagnostic.

Results concern this instrumented eager-mode service, one development trace, and one sampled response per problem/policy. They cannot establish the three-point accuracy tolerance or a production throughput improvement. Do not replace a serving baseline with the previous Transformers timings or automatically launch a follow-up based on this pilot.
