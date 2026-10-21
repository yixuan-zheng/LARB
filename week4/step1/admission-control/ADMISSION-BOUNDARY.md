# Step 1A: admission boundary

Inspected on PACE on October 21, 2026, against the existing `vllm-proof-env`
(vLLM 0.11.2). This is the implementation decision; GPU validation is recorded
separately under `results/`.

## Existing path and the gap

`week3/larb/burst-policy/server.py:64–76` reads `pressure.json` on HTTP receipt,
chooses an arrival budget, and puts it in `SamplingParams.extra_args['burst']`.
The old live policy also starts with this arrival budget. Its worker then applies
pressure immediately after adding a row, including with zero generated tokens.
That combines admission effects and later effects.

`week3/larb/burst-policy/adapter.py:93–115` delegates to the stock scheduler,
then writes a post-schedule snapshot containing the remaining waiting IDs and
the active IDs. `BurstProcessor.update_state` logs a worker `admitted` event;
this is not the point where stock scheduling first selects execution.

## Verified pinned engine interfaces

Paths below are relative to `vllm-proof-env/lib/python3.10/site-packages/`:

- `vllm/v1/core/sched/scheduler.py:660–664` builds `NewRequestData` for requests
  first scheduled in this step. Previously scheduled/resumed requests use cached
  request data. Chunked prefill does not create another first admission.
- `vllm/v1/core/sched/output.py`, `NewRequestData.from_request`, carries
  `request.sampling_params` into that output. `extra_args` can therefore carry
  the exact admission decision to the worker in the normal dispatch path.
- `vllm/v1/engine/core.py:338–339` calls `scheduler.schedule()` before
  `model_executor.execute_model(scheduler_output, non_block=True)`; the queued
  batch variant has the same ordering at lines 389–391.
- `vllm/v1/worker/gpu_model_runner.py:716–742` retains new-request sampling
  parameters. `gpu_input_batch.py:288–296` includes them in the added-row update;
  lines 743–748 deliver it to the logits processors.

`checks/inspect_runtime.py` records these installed-source hashes and focused
excerpts without importing vLLM or allocating a GPU.

## Intended order

1. HTTP receipt: arrival-only makes its fixed choice from the latest valid,
   phase-scoped snapshot. Full, admission, and live carry a long placeholder.
   A missing/stale arrival snapshot falls back to long and is logged.
2. Stock scheduling: delegate unchanged; determine new, active, and waiting
   requests. Publish that step's post-schedule snapshot.
3. **Admission decision, before dispatch:** for each `scheduled_new_reqs` entry,
   attach the step, waiting IDs, timestamp, and chosen budget to its
   `sampling_params.extra_args['burst']`. Admission and live use the same pure
   rule: short at two or more waiting requests, otherwise long. All requests
   first admitted together use the same post-schedule snapshot.
4. Dispatch/prefill: return the annotated scheduler output to the engine.
5. Worker initialization: consume the transported choice, never reconstruct it
   from the latest pressure file. Fail if admission metadata is absent. Record
   zero generated tokens and the originating admission step.
6. Generation: admission-only retains its choice. Live may reduce after positive
   output progress, using phase-scoped pressure. Natural closure or a cue already
   underway blocks further changes. The inherited forcing path finishes the full
   cue before ordinary answer sampling resumes.
7. Completion: retain raw tokens, client receipt, scheduler/worker events, source
   snapshots, and hashes. Budget reductions and actual cue starts remain separate.

The admission metadata is attached once, not on every worker row addition.
Worker state follows request identity across row moves and is retained on a
remove/readd. CPU fixtures exercise these paths; the smoke explicitly checks
whether preemption occurred rather than claiming GPU preemption coverage.

## Scope

No change to scheduling priority, batching, KV allocation, model, sampling,
transition text, or cap semantics. Week 3 is imported unchanged. A local
`bootstrap.py` resolves the repo's Week 3 tree; on PACE `LARB_WEEK3_ROOT` points
to the existing historical runtime tree, whose imported sources must match the
local source lock before the run starts.
