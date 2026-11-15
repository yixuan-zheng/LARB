# P1 report: GPU gate job

**Status:** P1 complete on GPU; P2 not started. Every gate below is a rig-validity or design
decision, not a hypothesis result.
**Job:** Slurm `7019318`, `ice-gpu`, 1 x H100 80 GB, 8 CPUs, 64 GB, 8 h allocation.
**Generated:** 2026-11-13 (America/New_York).
**Machine-readable:** `results/p1/gates.json`, `results/p1/source-lock.json`,
`configs/p1_freeze.json`; per-run records under `results/p1/runs/`, `results/p1/sweep/`,
`results/p1/calibration/`.

## 1. What ran

One gate job in the order of [plan/09-main-path.md](../plan/09-main-path.md): rig bridge, 32-row
mechanics, eager/graph equivalence, concurrency/throughput sweep, answer-contract bridge, slope
screen, load and deadline calibration. The engine is the frozen Qwen3-4B rev
`1cfa9a72...`, vLLM 0.11.2, 32 slots, 8,192 batched tokens, 12,288 context, prefix caching off,
a 429,744-token KV pool (0.85 utilisation; the largest observed demand, 32 x 8.3k, is about 266k
tokens or 62% of the pool), legacy contract unless the contract gate says otherwise. No arm
comparison was run, and no hypothesis is claimed.

The gate job also served as the first end-to-end execution of the P0 scaffolding. Eleven defects in
that scaffolding were found and fixed (§4). Each fix is a CPU-side correctness change; none
touches a threshold, budget or deadline.

## 2. Gate results

| Gate | Result | Evidence | Decision |
|---|---|---|---|
| P1.0 rig bridge | **pass** | fixed4k 33.3% (20/60) vs saved 36.7% (-3.4 pts), mean service 92.9 s (p90 117 s); fixed8k 46.7% (28/60) vs 45.0% (+1.7 pts), mean service 187.6 s (p90 266 s); tolerance 10 pts | Rig, prompt, cue and grading reproduce week 5 |
| P1.1 32-row mechanics | **pass** | 4 phases x 32 rows; 109 row moves; 113 forced cues, all at the exact budget position; 0 cue mismatches, 0 offset mismatches, 0 cuts after close; forced cue+cap phase 32/32 exact and 32/32 capped; second arrival order passes; preemption peak 0 | Controller and contract validated; no preemption occurred at 32 x 8k |
| P1.2 eager vs graphs | **fail token identity** | 32/32 records; 0/32 token sequences identical (first divergence as early as token 4); 29/32 cue positions identical; graph mean service 128.2 s vs eager 144.1 s (-11%) | Graphs are a different token-level experiment: **eager is the main path** |
| P1.3 throughput sweep | **pass (design)** | 4,096+128 tokens at concurrency 1/2/4/8/16/24/32 = 76.7/142.2/292.3/569.6/1,125.6/1,677.5/2,129.7 output tok/s; 8,192+128 at 16/24/32 = 1,053.4/1,472.3/1,751.3; zero preemptions at every point, GPU utilisation 44-75%, per-request decode 55-78 tok/s; 32 slots is the knee (gains 27% over 24) | Keep 32 slots; arm-average 1,940 tok/s; 4 seeds fit in ~9.0 h of output |
| P1.4 answer contract | **fail -> legacy** | legacy 4k 22.9% (22/96, cap 19.8%, median answer 1,398 tok) and 8k 38.5% (37/96, cap 14.6%, 1,128 tok); `short_boxed` 4k 6.3% (6/96, cap 46.9%, 85 tok) and 8k 8.3% (8/96, cap 49.0%, 106 tok); paired legacy-short +23.4 pts over 192 pairs, 47 discordant | The 128-token boxed contract truncates the answer and caps half the responses: **legacy stays** |
| P1.5 slope screen | **fail on the main-cohort preview** | disjoint 2023-2024 (48 q): 4k 20.8% (10/48), 6k 29.2% (14/48), 8k 41.7% (20/48), gain +20.8 pts, 70.8% of answers change, 8k cap 10.4%. Main-cohort preview (24 q): 4k 25.0% (6/24), 6k 29.2% (7/24), 8k 16.7% (4/24), gain -8.3 pts, 50% change, 8k cap 20.8% | The method carries a slope on 2023-2024 but the main pool does not: **P2 withheld**, change the pool |
| P1.6 calibration | **record: no 180 s band found** | fixed8k at 500/h (88 signal): 0.0% misses, 0% pressure, p90 latency 164.4 s; at 650/h (113 signal): 0.0%, 0%, p90 160.0 s; at 800/h (140 signal): 0.0%, 0%, p90 164.3 s; at 931/h (217 signal): 74.7% misses, 65.0% pressure, p50 229.9 s; at 1,164/h (272): 61.0%, 57.2%, p50 217.6 s; at 1,397/h (326): 88.3%, 82.2%, p50 455.6 s. The curve is a cliff, not a slope: service time rises with batch size, so 800/h has no queue and no misses while 931/h is overloaded. | The 180 s band is a very narrow strip between 800 and 931/h (a future grid must be ~820/860/900/h, or use the 240 s SLO, whose no-queue floor is 0% and whose band is wide). No rate is frozen |

All phases passed the injection guard (maximum injection lag 3 ms) and had zero request errors. Of the
912 gate responses, 645 audit as `normal`, 247 hit the answer cap, and 20 - all in the rejected
`short_boxed` arm - contain a second `</think>` and are treated as malformed. None is missing an
EOS, none has a cue mismatch, and no audit raised an exception.

**Outcome: P2 is withheld.** The rig gates validate the rig (P1.0, P1.1), Gate B rejects graphs
(token-level divergence), Gate C selects 32 slots, and Gate D rejects the short contract; Gate F is
a calibration record, not a pass/fail. Gate E fails the pre-registered pool criterion on the
24-item main-cohort preview. The disjoint 2023-2024 screen shows a +20.8-point 4k->8k gain and 70.8%
answer changes, so the method and the rig carry a slope; the 2025-2026 main pool does not reproduce
it (8k 16.7%, below the 35% floor, and 8k worse than 4k by two answers). With 24 items the preview
is small - 4/24 versus 6/24 is two responses - so this is a stop signal for this pool, not evidence
that the hypothesis is false. Gate F adds a second finding: at 180 s the miss rate is 0% at 500,
650 and 800 requests/h and 74.7% at 931/h, so the 15-40% band is a very narrow strip and the 240 s
SLO is the practical remedy. The next action is a pool change (Omni-MATH hard subset or another
event family) and a fresh preview, not a main run on this cohort.

**Decision (PLAN.md section 5):** this maps to the rule "Slope screen shows less than 8 points
between 4k and 8k ... the pool cannot carry the hypothesis -> change pool before measuring". P2 is
not run on this cohort; the rig decisions below are frozen for reuse; the next step is a new pool
and a fresh 24-item preview.

## 3. Frozen rig decisions and P2 status

**P2 is not authorised.** Gate E failed on the main-cohort preview, so per
[plan/09-main-path.md](../plan/09-main-path.md) §P1.5 the pool must change before any main run.
The rig decisions below are frozen and do not need to be re-measured; the pool and the preview do.
`configs/p1_freeze.json` records `p2_authorised: false`; `configs/p2_main.json` carries
`p2_status: "withheld"` and is not a ready-to-run configuration. The main sustained/burst traces
were **not** rebuilt at the calibrated rate, because there is no authorised run to use them.

Written to `configs/p1_freeze.json`, `configs/p2_main.json` and
`artifacts/source-lock-p1.json`; the gate records are hashed in the source lock.

| Item | Frozen value | Source |
|---|---|---|
| Concurrency | 32 (knee; 27% above 24) | Gate C |
| Seeds per question (pressure conditions) | 4 | Gate C |
| Answer contract | legacy (short boxed rejected: -23.4 pts) | Gate D |
| CUDA graphs | off (eager) | Gate B |
| Sustained arrival rate | none frozen at 180 s: 500/650/800 per hour give 0% misses and 931 gives 74.7%, so the 15-40% band is a narrow strip at about 850-900/h; the pre-declared 240 s fallback is the practical SLO for a next attempt | Gate F |
| Burst baseline / recovery rate | the eventual main rate (recorded, not frozen) | Gate F |
| Pressure threshold / persistence | 8 of 32 / 2 steps | P0 default; Gate F pressure fractions reported below |
| Cut target / floor / min saving | 4,096 / 512 / 1,024 | P0 protocol |
| SLO | 180 s from client arrival | P0 protocol |
| Cohort | 215 main questions, 24 preview held out | P0 cohort |
| P2 wall-time estimate | 9.0 h of output at 1,940 tok/s; at a ~850/h band rate the arrival span is 13.4 h with 4 seeds, 10.5 h with 3 and 7.6 h with 2, so a 180 s-SLO run would have to drop to 3 seeds or use the 240 s SLO | Gate C / Gate F |
| **P2 authorisation** | **withheld (Gate E)** | Gate E |

## 4. Defects found in the P0 scaffolding (all fixed before measurement)

The gate job was the first end-to-end execution of `code/larb_scaled`. The following were real
defects, each caught by a gate or a smoke request, not by inspection:

1. **`scheduler_cls` qualname.** vLLM resolves the scheduler with `module.Class` but logits
   processors with `module:Class`; the colon form failed at engine start.
2. **Row-state iteration.** `PressureProcessor.update_state` iterated `self.rows` (row indices)
   instead of `self.rows.values()` when collecting phases, crashing on the first request.
3. **Duplicate `monotonic` kwarg.** The scheduler emitted its snapshot through `emit(...)`, which
   also sets `monotonic`; the second scheduler step killed the engine.
4. **Missing `OUT` import** in the controller's new state writer.
5. **Cross-process state.** `AsyncLLM` always runs the engine core in a separate process in vLLM
   0.11.2, so the in-process bus is invisible to the HTTP layer. The controller now persists a
   small per-request state file at admission, cue, cut, cap and removal; the server reads it with
   a short retry. This also records `scheduler_start`, which was silently null before.
6. **Preemption state loss.** A preempted request left the batch and re-entered as a new
   `RequestControl`, restoring the original budget and losing the cut. State is now detached and
   reused on re-admission.
7. **Cap detection.** The controller forces EOS exactly at the answer cap, so the old
   `answer_tokens > cap` test never fired. Caps are now flagged by the controller and detected
   with `>=`.
8. **Client aborted the phase on one error.** A single failed request raised out of `gather` and
   killed the phase. Failures now produce a per-request record and stay in the denominator.
9. **Second server group wiped `phases.json`.** The aggregate was reset at the start of each
   group. It now appends, and the summariser can rebuild from `phases/*.json`.
10. **Orphaned engine cores.** vLLM's engine core detaches from the server's process group, so
    killing the server left ~70 GB allocated. The runner now kills the group and any orphaned
    `VLLM::EngineCore` owned by this user before starting the next group.
11. **Short-contract close counted as a cap.** `short_answer_closed` (the forced closing brace and
    EOS on an answer that finished inside the allowance) was treated as an answer cap, which would
    have inflated the short contract's cap rate by about 55 of 192 responses. Caught during Gate D
    and fixed before the gate was summarised: only `answer_cap`, or an answer at the allowance,
    counts as a cap.

Phase keys were also made unique per phase (graphs and contract phases previously reused request
keys and would have overwritten each other's records).

## 5. Deviations from the P0 gate plan

- **Gate trace spacing.** Quality-gate traces were densified (bridge 2 s, contract/screen/preview
  1.5 s between arrivals) so the whole line fits one allocation. These gates score per response;
  the deadline is 1,800 s and no SLO claim is made from them. The mechanics trace keeps 0.5 s
  spacing because it must build a full 32-row batch immediately.
- **Gate A gained a forced-cue/cap phase.** `mechanics-forced` runs the same 32 rows with a
  512-token budget and a 64-token answer cap, so the exact-cue and cap paths are exercised by
  construction rather than by hoping some question overruns 4k. The overrides are gate-only
  environment variables and are unset in P2.
- **Calibration grid derived from Gate C.** The P0 candidate rates (800/1,000/1,200 per hour)
  were written before any engine measurement. The bridge measured 187.6 s mean (p90 266 s) per
  fixed8k response and Gate C measured the aggregate rate, so the grid is set to 0.6/0.75/0.9 of
  the request capacity implied by the measured token rate. The 4,500-token mean understates the
  legacy contract's ~6,500 tokens per request, so the grid sits nearer capacity than the factor
  labels suggest; the measured points confirm it, and the miss rates, not the factors, decide.
- **Graphs disabled.** Gate B found divergent token sequences; the plan's rule keeps eager for the
  main run and reports graphs separately. The ~11% service-time advantage is recorded but not used.
- **The 180 s SLO is marginal at 8k.** No-queue signal service (queue wait under 5 s, n=53) is
  p50 165.7 s, p90 183.0 s, so the deadline already fails about 17% of responses with no queueing.
  At 931/h the queue adds the rest (74.7% signal misses, 217 responses). The 240 s fallback has a
  0% no-queue floor. The 180 s band therefore sits well below the candidate grid; a next calibration
  should start near 500-750/h at 180 s, or use the pre-declared 240 s SLO.
- **Service time rises with batch size.** At 500/h (~18 concurrent) the signal p90 service is 164 s
  and the 180 s miss rate is 0%; at 931/h (32 concurrent) the no-queue p90 is 183 s and p50 latency
  including the queue is 230 s. The deadline is therefore not a fixed property of a request: it
  depends on the offered load through batching. This is why the miss curve jumps between the lower
  points and 931/h rather than rising smoothly, and why a future calibration must sweep finely
  around that knee.
  three to five minutes are below steady state and the realised miss rate depends on when the
  Poisson draw fills the 32 slots. The three points are a coarse bracket, not a clean curve. A next
  calibration should warm the queue for five minutes or measure only the last ten minutes of each
  point, and the per-phase `phase.json` should say which window was scored.

## 6. Records and reproduction

```
results/p1/
  runs/bridge/      2 phases x 60 responses; requests/, request-state/, scheduler.jsonl, worker.jsonl
  runs/mechanics/   4 phases x 32 responses; same layout
  runs/graphs/      2 phases x 32 responses; same layout, one per engine mode
  runs/contract/    4 phases x 96 responses; one per contract and budget
  runs/slope/       6 phases (48-item screen and 24-item preview x 3 budgets)
  sweep/            throughput.json (points, GPU memory, preemptions), scheduler.jsonl
  calibration/
    rates/          3 x 20-minute fixed8k replays at candidate rates
    live/           30-minute live-arm manipulation check at the chosen rate (skipped: no rate in band)
    calibration.json, traces/ (hashed calibration traces)
  calibration-lower/  follow-up fixed8k points at 500 and 650 per hour (the lower grid implied by rates/)
  calibration-mid/    follow-up fixed8k point at 800 per hour (brackets the cliff between 650 and 931)
  gates.json        every gate's metrics and pass flag
  source-lock.json  config, code, artifact, model and GPU hashes
configs/p1_freeze.json   the frozen decisions
artifacts/traces/        sustained, burst, low + gate traces, with manifest hashes
artifacts/freeze.json    code/config/artifact freeze manifest (P1 supersedes the P0 CPU freeze)
```

Every request record carries the runtime key, condition, arm, class, question, seed, budgets, final
budget, cut events, cue position, token ids, finish reason, cap flag, queue depth at admission,
scheduler start, preemption count and grading reference. The request-state files are the
cross-process channel from the engine core; they are kept because they are the only place where
`scheduler_start`, `cue_start`, cut history and the cap flag are recorded together.

Reproduce the gate decisions on CPU with the analysis venv:

```sh
PY=/storage/.../LARB-week5-env/analysis-venv/bin/python
PYTHONPATH=week7/scaled-serving/code $PY week7/scaled-serving/code/tools/summarize_gates.py \
  --runs week7/scaled-serving/results/p1/runs \
  --sweep week7/scaled-serving/results/p1/sweep \
  --calibration week7/scaled-serving/results/p1/calibration \
  --out week7/scaled-serving/results/p1/gates.json
PYTHONPATH=week7/scaled-serving/code $PY week7/scaled-serving/code/tools/calibrate_load.py \
  --stage summarize --out week7/scaled-serving/results/p1/calibration
PYTHONPATH=week7/scaled-serving/code $PY week7/scaled-serving/code/tools/calibrate_load.py \
  --stage summarize --out week7/scaled-serving/results/p1/calibration-lower
```

The grader is `math_verify` 0.9.0 with the boxed-answer extractor; graded flags are stored next to
the raw text so a later regrade does not need the GPU.

## 7. What the next attempt must change, and what to carry forward

**The blocker is the pool, not the rig.** Gate E's preview shows the 2025-2026 main cohort at 8k
accuracy 16.7% (4/24) with no 4k->8k gain. Before any main run:

1. Replace the main cohort with a pool that shows a budget slope on a *preview*, per
   [plan/09-main-path.md](../plan/09-main-path.md) §P1.5: the Omni-MATH hard subset (filtered by
   source and published difficulty, never by observed accuracy) or another 2025-2026 event family.
2. Re-run only the preview half of Gate E (24 items x 4k/6k/8k, one seed) on the new pool; that is
   a ~10-minute GPU check, not another whole gate job.
3. Only if the new preview passes, rebuild the main traces at the calibrated rate, freeze, and run
   P2. The rig gates (A-D) do not need repeating unless the code or engine changes.

**Carry forward unchanged:** 32 slots, eager, legacy contract, 4 seeds, threshold 8 of 32 with
2-step persistence, cut target 4,096 with floor 512 and minimum saving 1,024, the 180 s SLO, and the
measured 1,940 tok/s arm-average rate. The calibrated arrival rate in §3 is a property of the rig
and the SLO, not of the failed pool, so it can be reused as the starting point for the new pool's
calibration.

**Watch items for the eventual main run:**

- **Preemption was not observed** in Gate A at 32 x 8k (peak 0). If the main traffic produces
  preemption, it must be reported per arm next to the score; a shorter budget that avoids
  preemption is a mechanism, not noise.
- **The legacy answer cap is real but not dominant:** 19.8% of 4k and 14.6% of 8k contract responses
  hit the 2,048-token cap (median answer 1,398 and 1,128 tokens). H3's accuracy cost is partly a cap
  cost; the short-answer alternative is not available because Gate D rejected it by 23 points.
- **Graphs are off.** If a later job has spare time, a graph replication is a separate experiment,
  not a mid-run switch.
- **One block, one model, one GPU.** The fresh subset (80 items) is analysed separately from the
  recent/exposed subset; a difference between them is a finding, not a nuisance.
- **The realised seed count and arrival rate must be read from `phase.json`**, not from this
  document, if any phase is rerun.
- **The preview decision is made on 24 items.** A near-miss on a future preview (for example 5
  points of gain) should trigger a larger preview before a main run, not a threshold change after
  the fact.
