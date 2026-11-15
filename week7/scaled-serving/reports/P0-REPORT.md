# P0 report: CPU-side scaled serving rig

**Status:** P0 complete on CPU; P1 GPU execution not started.
**Generated:** 2026-11-13.
**Machine-readable status:** `results/p0/cpu_checks.json`.
**Freeze:** `artifacts/freeze.json`.
**No GPU job was submitted and no model inference was run.**

## 1. What was completed

| P0 item | Result |
|---|---|
| P0.1 protocol | `configs/protocol.json`; arms, budgets, pressure, deadline, conditions, seeds, analysis |
| P0.2 datasets | 12 pools fetched, hashed, normalized; `data/raw/manifest.json`, `data/processed/manifest.json` |
| P0.3 traces | low/sustained/burst + five P1 gate traces; `artifacts/traces/manifest.json` |
| P0.4 code and tests | `code/larb_scaled/`; 40 CPU tests pass |
| P0.5 rehearsal | `code/tools/synthetic_rehearsal.py`; design-time pressure/miss estimates in `results/p0/synthetic.json` |
| P1 scaffolding | phase planner, replay client, server/controller adapters, dry-run plans, sbatch drafts |
| Consolidation | one report (this file), one status JSON, one freeze manifest, logs/results separated |

## 2. Frozen protocol

- **Arms:** `fixed4k`, `fixed8k`, `arrival`, `live`. `fixed6k` is a calibration/extension arm and is
  available for the P1 slope screen.
- **Budgets:** short 4,096; long 8,192; cut target 4,096; filler 1,024.
- **Pressure:** `waiting >= max(4, ceil(0.25 * max_num_seqs))` = 8 of 32, for 2 consecutive
  scheduler steps. Calibration may choose 4/8/12 from the pre-declared grid.
- **Cut:** one eligible request per scheduler step; largest remaining budget; progress floor 512;
  minimum saving 1,024; one-way; never after close; never at/below target.
- **Admission:** `arrival` and `live` share the same queue-aware rule (8k below threshold, 4k at or
  above). `live` adds the in-flight cut. This keeps H2 an in-flight test.
- **Conditions:** `low`, `sustained`, `burst/recovery`. Deadline is 180 s from client arrival;
  fallback 240 s only if calibration cannot produce a 15-40% reference miss band.
- **Pairing:** same question and seed across arms; phase order rotated; one block is the main path.
- **Answer contract:** legacy 2,048-token contract is the default; `short_boxed` is gated by the
  P1 384-response bridge.

## 3. Data

Twelve dataset snapshots were fetched and hashed. Every pool records its revision, source-file
SHA-256, row count, license and exposure tag.

| Pool | Rows | Role | License | Exposure |
|---|---:|---|---|---|
| MathArena/aime_2026 | 30 | main | cc-by-nc-sa-4.0 | fresh |
| MathArena/hmmt_feb_2025 | 30 | main | cc-by-nc-sa-4.0 | recent |
| MathArena/hmmt_nov_2025 | 30 | main | cc-by-nc-sa-4.0 | fresh |
| MathArena/hmmt_feb_2026 | 33 | main | cc-by-nc-sa-4.0 | fresh |
| MathArena/smt_2025 | 53 | main | cc-by-nc-sa-4.0 | recent |
| MathArena/brumo_2025 | 30 | main | cc-by-nc-sa-4.0 | recent |
| MathArena/cmimc_2025 | 40 | main | cc-by-nc-sa-4.0 | recent |
| MathArena/aime_2025 | 30 | bridge | cc-by-nc-sa-4.0 | exposed |
| MathArena/aime_2023_I | 15 | screen | cc-by-nc-sa-4.0 | exposed |
| MathArena/aime_2023_II | 15 | screen | cc-by-nc-sa-4.0 | exposed |
| MathArena/hmmt_feb_2024 | 30 | screen | cc-by-nc-sa-4.0 | exposed |
| HuggingFaceH4/MATH-500 | 500 | filler | not declared on card | exposed |

MATH-500 has no license field on its dataset card; record that gap rather than inventing one.

**Cohort after exclusions:** 239 eligible main items, 24-item preview, **215 main**; **30 bridge**;
**48 screen**; **92 filler** (used cyclically with distinct seeds). Seventeen items were excluded:
13 diagram-dependent and 4 proof-like. No item was excluded on a model outcome. The bridge keeps
all 30 AIME 2025 items for comparability; any diagram/proof flag is recorded in `bridge_flag`.

## 4. Traces

All traces are JSONL, sorted by arrival, arm-agnostic and SHA-256 frozen. Main traces are
**provisional** until P1 Gate F calibrates the arrival rate. Gate traces use a loose 1,800 s
deadline because they score quality, not SLO attainment.

| Trace | Requests | Signal | Filler | Last arrival | Notes |
|---|---:|---:|---:|---:|---|
| low | 172 | 120 | 52 | 2,062 s | no-queue control; 60 questions x 2 seeds |
| sustained | 1,229 | 860 | 369 | 5,177 s | 215 questions x 4 seeds; provisional 810/h |
| burst | 1,229 | 860 | 369 | 6,044 s | baseline 700/h, 90-request burst at 600 s |
| gate-bridge | 60 | 60 | 0 | 472 s | 30 AIME 2025 x 2 seeds |
| gate-screen | 48 | 48 | 0 | 376 s | 48 disjoint screen items |
| gate-preview | 24 | 24 | 0 | 184 s | 24 main-cohort preview items |
| gate-contract | 96 | 96 | 0 | 760 s | 48 items x 2 seeds |
| gate-mechanics | 32 | 32 | 0 | 16 s | 32-row mechanics trace |

## 5. Design-time rehearsal

`code/tools/synthetic_rehearsal.py` runs a FIFO 32-server model with an explicit,
deliberately pessimistic service assumption: signal ~lognormal(median 150 s, p90 220 s), filler
~lognormal(35 s, 55 s). This is **not** a measured result; it checks that the traces exercise the
intended regimes.

| Condition | Utilisation | Pressure fraction | Max waiting | Overall miss | Signal miss |
|---|---:|---:|---:|---:|---:|
| low | 0.29 | 0.00 | 1 | 17.4% | 25.0% |
| sustained | 0.85 | 0.15 | 20 | 26.9% | 38.4% |
| burst | 0.75 | 0.18 | 96 | 37.5% | 45.6% |

The low control has zero pressure. Sustained and burst have non-trivial pressure and signal miss
rates near the upper edge of the 15-40% target. The burst signal miss rate is high under this
pessimistic service assumption; P1 Gate F must lower the load or the burst count if the real
engine reproduces it. The real engine's service distribution is expected to differ.

## 6. CPU validation and power

- **40/40 unit tests pass**: contract/cue/cap, row moves, pressure persistence, cut selection,
  admission, trace generation/validation, grading, bootstrap/sign tests, analysis fixtures,
  config/protocol.
- **12/12 dataset manifests** present, no fetch failures, 12 source hashes, 11 declared licenses.
- **8/8 traces** validate and match their manifest hashes.
- **Protocol validation** passes.
- **Power:** at 215 questions x 4 seeds, effective pairs are about 537 at ICC 0.2, 391 at ICC 0.4
  and 307 at ICC 0.6; the 80% MDE at 20% discordance is about 5.4, 6.3 and 7.1 points. The main
  path is powered for 5-6 points, not 3. The 500-800 question extension is still the only route to
  a 3-point claim.
- **Freeze:** `artifacts/freeze.json` records code, config and artifact hashes.

## 7. P1 readiness

The following pieces exist and have CPU-side plans:

- `code/larb_scaled/server.py`: vLLM HTTP service with queue-aware admission, phase endpoint,
  request records and controller dispatch.
- `code/larb_scaled/controller.py`: vLLM scheduler snapshot and logits-processor adapter; pure
  contract/policy logic is tested separately.
- `code/larb_scaled/client.py`: asyncio replay client with injection-lag and drain checks.
- `code/larb_scaled/runner.py`: `--dry-run` plans for `p2-main` and `p1-gates`; GPU execution starts
  the local server, runs phases, and analyzes.
- `code/sbatch/`: gate and main drafts (not submitted).

P1 still requires GPU execution and the two gate scripts not yet implemented as phase plans:
throughput/concurrency sweep and load/deadline calibration. Their configurations are in
`configs/p1_gates.json`; they should be run before the main job. The P1 gate plan currently covers
bridge, mechanics, eager/graph equivalence, answer-contract bridge, and slope/preview.

`results/p0/p1_readiness.json` records the CPU-side readiness check: every Python file compiles,
both sbatch drafts pass `bash -n`, the P1 plan has 16 phases / 848 requests, the P2 plan has 12
phases / 10,520 requests, the model path exists, and `nvidia-smi` is absent on the login node as
expected. `results/p0/p1-sweeps-plan.json` records the throughput and calibration plans (14
throughput points, three calibration rates).

## 8. Commands

```sh
# CPU tests and P0 status
PYTHONPATH=week7/scaled-serving/code python3 -m unittest discover \
  -s week7/scaled-serving/code/tests -p 'test_*.py'
PYTHONPATH=week7/scaled-serving/code python3 \
  week7/scaled-serving/code/tools/run_cpu_checks.py

# P0 -> P1 dry-run plans
PYTHONPATH=week7/scaled-serving/code python3 -m larb_scaled.runner \
  --stage p2-main --out week7/scaled-serving/results/p0/dry-run-p2 --dry-run
PYTHONPATH=week7/scaled-serving/code python3 -m larb_scaled.runner \
  --stage p1-gates --out week7/scaled-serving/results/p0/dry-run-p1 --dry-run
```

The GPU entrypoint is the same runner without `--dry-run`, under a Slurm allocation. It does not
submit jobs itself.

## 9. Issues to resolve before P1 measurement

1. **Calibrate sustained/burst load on the real engine.** The provisional synthetic burst signal
   miss rate is 45.6%, above the target band; Gate F must adjust load before freezing the main
   trace.
2. **Exact prompt token counts.** P0 uses the local `tokenizers` file plus a 32-token chat-template
   allowance; the server performs the exact chat-template/context check at runtime.
3. **Short-answer contract.** The legacy contract is active by default. The 384-response bridge
   decides whether `short_boxed` may replace it.
4. **GPU-only gates.** Throughput sweep and load calibration are configured but not yet executed.
5. **MATH-500 license.** The dataset card does not declare one; the manifest records null.
6. **No GPU validation yet.** Controller row moves, graph equivalence, exact cue positions and
   preemption telemetry remain P1 gates, not P0 claims.

