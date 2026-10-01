# Week 1: FFN width latency profile

Does swapping a wide Gemma 3n FFN for a statically sliced narrow one make serving faster,
and if so under exactly which workloads? The preflight package established that the sliced
sub-models are *numerically* sound (dynamic == static with `max_abs_logit_error: 0.0`) but
found a ~1.0x Large/Small latency ratio at batch 1 with short prompts. This directory
profiles that ratio properly instead of concluding from a single unvalidated setup.

Scope discipline, stated up front:

* **Statically extracted sub-models first, then a dynamic-switching extension.** S0-S7
  measure one FFN width per process; three workers (`small` E2.98B, `medium` E3.49B,
  `large` E3.98B) are built from the published presets. **S8-S11** (below) measure the
  cost and the value of *changing that width per iteration* on a single full-weight model,
  and compare it against exactly these static baselines.
* **Text only**, via `Gemma3nForCausalLM`. The multimodal class peaks at ~15.6 GiB on load
  and its vision/audio towers do no work here.
* **Not a serving benchmark.** Single process, eager PyTorch unless a scenario opts into
  another backend, no continuous batching, no runtime.

## Layout

| File | Role |
|---|---|
| `latency_math.py` | stdlib-only statistics + analytic FLOP/byte model (no torch, testable anywhere) |
| `latency_lib.py` | torch/CUDA side: manifest, incremental records, interleaved harness, clock guard |
| `build_worker.py` | static sub-model extraction from one parent load |
| `s0_harness_validation.py` | **gate**: proves the instrument resolves a known effect and invents none |
| `s1_decode_step.py` | decode-step latency vs context length, batch 1 (the negative control) |
| `s2_prefill.py` | prefill latency vs prompt length and batch (the best case for a width win) |
| `s3_batch_decode.py` | batched decode, ITL and tokens/second |
| `s4_end_to_end.py` | TTFT, ITL distribution, end-to-end latency, throughput, peak VRAM |
| `s5_backends.py` | eager vs `torch.compile` vs CUDA Graphs; tests whether host dispatch hides the effect |
| `s6_layer_profile.py` | per-layer FFN runtime, module attribution, analytic speedup ceiling |
| `s7_memory_roofline.py` | weights by component, KV/token, max batch before OOM, achieved BW and MFU |
| `dynamic_lib.py` | dynamic extension: `SwitchController` (per-iteration FFN width on one full-weight model), scheduled generation, static-reference builders |
| `switch_schedules.py` | stdlib-only width plans and schedule generators (const/alternate/block/random/phase); testable on a login node |
| `s8_switch_mechanism.py` | **gate**: dynamic-at-W vs static-W logits, switch-operation cost, mechanism tax (`view` vs `materialize`), cold-switch penalty, null control |
| `s9_switch_phase.py` | one switch at the prefill/decode boundary; prefill-win "capture fraction" and boundary cost |
| `s10_switch_iteration.py` | per-token decode switching (alternate/block/random); alternation overhead vs the width-weighted static prediction |
| `s11_switch_flexibility.py` | weights per option, max batch before OOM, retarget cost: what one switchable weight set buys |
| `test_switch_schedules.py` | CPU-only correctness tests for the schedule algebra (24 checks) |
| `analyze_latency.py` | aggregates everything into CSVs plus a fitted `T = a + b*tokens + c*kv + d*weights`; extracts s0/s4/s6/s7 detail and a coverage audit; also emits `switch_summary.json` |
| `test_flop_model.py` | CPU-only correctness tests for the cost model (32 checks) |
| `run_suite.sh` | driver; one process per preset for S6/S7 |
| `report_latency.py` | renders the aggregated JSON into `results/latency_report.md`, ending with provenance and any coverage gap |
| `run_session.sh` | driver for one allocation, sized from measurement, with per-scenario `timeout` guards and a status file; set the `SCENARIOS` env var to resume a subset |
| `probe_cost.py` | measures real per-configuration cost (prefill, decode, seconds per iteration) so a grid is sized from data rather than guessed |
| `env.sh` | checkpoints and caches under `MATFORMER_PROJECT_ROOT` (mirrors `preflight`) |
| `run-output/` | Git-ignored; every measurement is flushed as it lands |
| `results/` | archived CSVs, aggregated JSON, per-scenario extracts, and the cost-model test record |

## Running

```bash
source week1/latency-baselines/env.sh          # HF cache + venv, per preflight convention
python week1/latency-baselines/test_flop_model.py       # CPU-only, seconds, no GPU needed
python week1/latency-baselines/test_switch_schedules.py # CPU-only, schedule algebra

bash week1/latency-baselines/run_suite.sh fast      # gate + tiny grids
bash week1/latency-baselines/run_suite.sh full      # the intended grid

PRESETS="small,large" bash run_suite.sh full        # if all three workers will not fit
SCENARIOS="s1 s3" bash run_suite.sh fast            # any subset
SCENARIOS="s8" bash run_suite.sh fast               # dynamic gate only (run it before s9-s11)
```

Run on an allocated GPU node, never a login node (the checkpoints are ~16 GiB and S2/S3
can reach tens of GiB of VRAM; this mirrors `preflight/environment/SETUP.txt`).

## What each scenario answers

* **S0** — can the harness be trusted? It must recover a known 2x compute difference, show
  no significant difference between identical workloads, and produce a tight linear fit of
  `T` against bytes moved. It also reports the harness's own floors: fixed per-call
  overhead (`alpha`), residual bias, and the minimum detectable difference.
* **S1** — the pilot's regime. Expected to be flat; its value is `alpha` and the MDD.
* **S2** — prefill. Highest arithmetic intensity, so the best case for a width win.
* **S3** — batch. Where a byte saving converts into tokens/second.
* **S4** — the quotable numbers: TTFT, ITL p50/p90, E2E, tok/s, peak VRAM.
* **S5** — the decisive test. If `alpha` is what hides the effect, removing it must move the
  ratio toward the 0.714 weight ratio.
* **S6** — attribution and the ceiling: a width change touches one of ~13 units per layer,
  so `ceiling_speedup = 1 / (1 - ffn_time_share * (1 - 0.714))` bounds the win at that
  grid (a grid with lighter attention has a larger FFN share, hence a higher ceiling).
* **S7** — the memory side, which is arithmetically certain even where latency is not:
  6.56 GiB vs 4.69 GiB of FFN weights, plus max batch and context at fixed capacity.
* **S8** — the dynamic gate. Proves a runtime-width model is *numerically identical* to the
  static baselines (dynamic-at-W == static-W, `max_abs_logit 0.0`, on the L40S), prices the
  switch itself (host `apply`, ~87 us for 35 layers), and reports the *mechanism tax*
  (dynamic-at-W vs static-at-W, per `slice_mode`) and the cold-switch penalty.
* **S9** — the flexibility win that the static suite cannot express: narrow prefill then one
  switch to wide decode. Reports the `capture_fraction` of the static prefill win banked and
  what the boundary switch adds to the next token.
* **S10** — iteration-level switching inside decode: alternate/block/random schedules; its
  headline number is the *alternation overhead* against the width-weighted static prediction,
  i.e. what switching every token costs beyond the widths being switched between.
* **S11** — what one switchable weight set buys: weights per option, max batch before OOM, and
  the retarget cost (a host `apply`) against a full reload.

### Dynamic switching (s8-s11): method

S8-S11 reuse every instrument (clock guard, L2 flusher, dual-clock timer, interleaved
shuffled sampling, crash-safe records) and add a `SwitchController` that keeps the *full*
E4B weights resident and serves any per-layer width by slicing at call time. The switch is
a per-layer attribute write, timed on the host and reported separately from the step. Two
design points matter for honesty:

* **Contiguity is an axis, not a footnote.** `slice_mode=view` is the preflight pilot's
  strided-view path; `materialize` caches contiguous slices. Reporting both stops a
  contiguity penalty from being mislabelled as "the cost of switching" (the static workers
  already call `.contiguous()` for exactly this reason).
* **Cold and warm are separated.** A switch touches no device state; the only possible cost
  is the shape change on the *next* forward, so cold-switch is measured deliberately on
  prefill (decode is always warm, because building the cache runs a forward first).

The dynamic model is the `large` worker (all layers 16384), and each preset is a legal slice
of it, so one resident weight set emulates all three presets; static references for `small`/
`medium` are built from the same single parent load.

## Measurement methodology

Cheap to state, expensive to get wrong:

* **Clock guard.** This L40S idles at ~210 MHz SM; a run aborts or warns unless the SM
  clock reaches `--min-sm-clock-mhz` (1500-2000 recommended) after a forced ramp.
* **Warmup then repetitions**, with **per-iteration samples retained** (medians plus whole
  distributions, never a single number).
* **Shuffled interleaving.** Each configuration contributes one sample per round in a
  reshuffled order, so clock/thermal drift cannot masquerade as an effect and the paired
  statistics are valid. S0 measured a ~1.4% minimum detectable difference and a ~0.9%
  residual bias.
* **Both clocks on the same call.** `wall_ms` (perf_counter, GPU-synchronised) and `gpu_ms`
  (CUDA events). Their difference is reported as `alpha_ms`, the host dispatch cost, which
  is the single most explanatory quantity in this profile.
* **Constant cache length.** Every measured decode step is preceded by an untimed prefill,
  so it always sees exactly `ctx_len` cached tokens: no growth across reps, no dependence
  on the previous iteration, identical across presets.
* **L2 flushed between iterations** by rewriting a 512 MiB scratch buffer (L40S L2 is 96 MB),
  outside the timed region. Flushing is conservative, so `--no-flush-l2` is provided and S0
  reports whether the flush is even detectable at microbenchmark scale.
* **Fixed algorithm selection** (`cudnn.benchmark = False`) so kernel choice does not differ
  with width and become a confound.
* **Pre-registered claim rule.** A difference is called `appreciable` only if the paired
  bootstrap CI excludes 1.0 *and* the median delta exceeds 2%. Everything else is reported
  as `within_noise`. S0 supplies the empirical floor to justify the 2% threshold.
* **VRAM budgeting.** Grid points whose activation estimate exceeds a fraction of free VRAM
  are skipped and recorded with the reason, rather than crashing a multi-hour sweep.

## Early findings already in hand

* **Corrected by measurement, not carried over from S0.** S0 measures ~87 us of fixed cost
  per *isolated* kernel call, but that does **not** transfer to a model forward: S1 measures
  `alpha` at only **~35 us**, because launches overlap with device work. So the pilot's flat
  ratio is not a host-dispatch artefact. The step is ~54 ms of genuine device time at
  **~26-31% of DRAM peak** and **~0.03-0.04% MFU**: latency-bound on a long chain of small
  kernels, not bandwidth-bound. This is exactly the kind of inherited assumption the
  suite's own S0/S1 pair exists to catch.
* A wider GEMM is *relatively more efficient* (a 2x large GEMM took 2.17x, not 2.0x), so
  width reduction fights a geometric-efficiency penalty as well as enjoying a byte saving.
* The text model is **13.73 GiB** of weights (the `large` preset; `small` is 11.86 GiB), of
  which **5.38 GiB is embedding tables** that no width change touches. Narrowing the FFN moves
  ~1.88 GiB, about 14% of residency.
* The FFN is **88.6%** of linear-layer FLOPs at a 2048-token context, yet removing ~14% of the
  weight bytes (large 13.73 GiB -> small 11.86 GiB, both matching the analytic model exactly)
  moves a batch-1 decode step by **0.7% at 128 context and 0% at 512** (S1 smoke run). The
  arithmetic is large and the byte saving is real; neither is what the step time is spent on.
  S6 is the scenario that explains where it does go.
* **Dynamic switching is measured on the full session grid (S8-S11, L40S).** The switchable
  model is *numerically identical* to the static baselines in-process (`max_abs_logit 0.0` at
  large, medium and small); the switch costs ~87 us of host time for all 35 layers; and the
  mechanism tax (dynamic-at-W vs static-at-W, `view` and `materialize`), the cold-switch
  penalty, and a two-identical-conditions null control are all `within_noise` (|tax| <= ~1.5%).
  On the schedule side a single switch at the prefill/decode boundary **captures 0.99-1.01x of
  the static prefill win wherever that win is resolvable** (S9: 0.991 @L2048_B1, 0.994 @L2048_B4,
  1.008 @L512_B4; at L512_B1 the static win is 0.39 ms and the fraction is reported `n/a`), and
  per-token alternation costs **<= 0.06%** (S10). S10 also shows the static large-vs-small
  *decode* widths are themselves unresolvable (|delta| < 0.34 ms), so that ~0 is "nothing to
  lose in decode", not "switching is free everywhere" -- the report states this explicitly.
  S11 quantifies the flexibility: one 13.73 GiB switchable weight set emulates all three presets
  where two static models need 25.59 GiB (at +1.88 GiB over small-only), and its max batch is
  unchanged vs a static worker even with only one model resident at a time (cap-limited at
  short context, activation/KV-bound at long context).

## Reading the output

`run-output/<scenario>__<preset>__<tag>.json` holds the manifest (argv, git SHA, versions,
versions, device, clocks, protocol), every raw sample, summaries, comparisons and derived
utilization. `completed: true` distinguishes a finished run from a preempted one. Then:

```bash
python analyze_latency.py      # -> results/latency_profile.{json,csv} + per-scenario detail
python report_latency.py       # -> results/latency_report.md
```

`analyze_latency.py` writes one extract per scenario into `results/`, so no
conclusion-determining number lives only in `run-output/`:

| file | contents |
|---|---|
| `results/latency_profile.json` | the whole aggregated structure (utilization, comparisons, `end_to_end`, `attribution`, `memory`, `gates`, `switching`, `summary.coverage`) |
| `results/latency_profile.csv`, `results/comparisons.csv` | utilization and paired Large-vs-Small rows (s1, s2, s3, s5, s7) |
| `results/s4_end_to_end.csv`, `results/s4_end_to_end_ratios.csv` | TTFT/ITL/e2e/throughput per request, plus the cross-process width ratio |
| `results/s6_attribution.csv` | per-module shares, kernel-category shares and the analytic speedup ceiling |
| `results/s7_memory.csv` | resident weights per bucket, KV per token, capacity cap, roofline utilization |
| `results/scenario_coverage.csv` | rows each scenario contributed to each table (a scenario that produced none is named) |
| `results/crossover.json`, `results/switch_summary.json` | the fitted cost model and the s8-s11 switching blocks |

`report_latency.py` renders every scenario that ran, leads with a `Verdicts at a
glance` table, prints the `Coverage` accounting (including any scenario present in
the records but missing from every table) and closes with a `Provenance` table
mapping each block back to its raw record. `results/crossover.json` contains the
fitted model and the implied width effect; the CSVs are plottable with whatever
tooling the reader prefers (no new dependency is imposed).
