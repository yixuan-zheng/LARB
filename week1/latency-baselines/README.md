# Week 1: FFN width latency profile

Does swapping a wide Gemma 3n FFN for a statically sliced narrow one make serving faster,
and if so under exactly which workloads? The preflight package established that the sliced
sub-models are *numerically* sound (dynamic == static with `max_abs_logit_error: 0.0`) but
found a ~1.0x Large/Small latency ratio at batch 1 with short prompts. This directory
profiles that ratio properly instead of concluding from a single unvalidated setup.

Scope discipline, stated up front:

* **Statically extracted sub-models only.** One FFN width per process; three workers
  (`small` E2.98B, `medium` E3.49B, `large` E3.98B) built from the published presets.
* **No dynamic switching and no switching-cost measurement.** That is a separate question.
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
| `analyze_latency.py` | aggregates everything into CSVs plus a fitted `T = a + b*tokens + c*kv + d*weights` |
| `test_flop_model.py` | CPU-only correctness tests for the cost model (31 checks) |
| `run_suite.sh` | driver; one process per preset for S6/S7 |
| `run_session.sh` | driver for one allocation, sized from measurement, with per-scenario `timeout` guards and a status file; set the `SCENARIOS` env var to resume a subset |
| `probe_cost.py` | measures real per-configuration cost (prefill, decode, seconds per iteration) so a grid is sized from data rather than guessed |
| `report_latency.py` | renders the aggregated JSON into `results/latency_report.md` |
| `env.sh` | checkpoints and caches under `MATFORMER_PROJECT_ROOT` (mirrors `preflight`) |
| `run-output/` | Git-ignored; every measurement is flushed as it lands |
| `results/` | archived CSVs, aggregated JSON, and the cost-model test record |

## Running

```bash
source week1/latency-baselines/env.sh          # HF cache + venv, per preflight convention
python week1/latency-baselines/test_flop_model.py   # CPU-only, seconds, no GPU needed

bash week1/latency-baselines/run_suite.sh fast      # gate + tiny grids
bash week1/latency-baselines/run_suite.sh full      # the intended grid

PRESETS="small,large" bash run_suite.sh full        # if all three workers will not fit
SCENARIOS="s1 s3" bash run_suite.sh fast            # any subset
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
  so `ceiling_speedup = 1 / (1 - ffn_time_share * (1 - 0.714))` bounds every claim.
* **S7** — the memory side, which is arithmetically certain even where latency is not:
  7.05 GiB vs 5.03 GiB of FFN weights, plus max batch and context at fixed capacity.

## Measurement methodology

Cheap to state, expensive to get wrong:

* **Clock guard.** This L40S idles at ~210 MHz SM; a run aborts or warns unless the SM
  clock reaches `--min-sm-clock-mhz` (1500-2000 recommended) after a forced ramp.
* **Warmup then repetitions**, with **per-iteration samples retained** (medians plus whole
  distributions, never a single number).
* **Shuffled interleaving.** Each configuration contributes one sample per round in a
  reshuffled order, so clock/thermal drift cannot masquerade as an effect and the paired
  statistics are valid. S0 measured a ~1.4% residual bias before shuffling.
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
* The text model is **12.73 GiB** of weights, of which **5.38 GiB is embedding tables** that no
  width change touches. Narrowing the FFN moves ~2 GiB, about 15% of residency.
* The FFN is **88.6%** of linear-layer FLOPs at a 2048-token context, yet removing 15% of the
  weight bytes (large 13.73 GiB -> small 11.86 GiB, both matching the analytic model exactly)
  moves a batch-1 decode step by **0.7% at 128 context and 0% at 512** (S1 smoke run). The
  arithmetic is large and the byte saving is real; neither is what the step time is spent on.
  S6 is the scenario that explains where it does go.

## Reading the output

`run-output/<scenario>__<preset>__<tag>.json` holds the manifest (argv, git SHA, versions,
versions, device, clocks, protocol), every raw sample, summaries, comparisons and derived
utilization. `completed: true` distinguishes a finished run from a preempted one. Then:

```bash
python analyze_latency.py      # -> results/latency_profile.{json,csv}
python report_latency.py       # -> results/latency_report.md
```

`results/crossover.json` contains the fitted model and the implied width effect; the CSVs
are plottable with whatever tooling the reader prefers (no new dependency is imposed).
