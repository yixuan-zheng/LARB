# Decode study

**October 7, 2026 — PACE, one NVIDIA L40S, Gemma 3n E4B, bf16.**

The timing screen found weak end-to-end decode savings in the current eager
runtime. Profiling explains why: FFN narrowing reduces GPU work, but runtime gaps
at batch 1 and attention/cache work at batch 64 limit the latency benefit.
An optimized runtime is a concrete follow-up; a larger model alone is not yet
justified. These experiments do not establish an advantage for per-iteration width
adaptation over a schedule chosen once per request.

## Timing screen

Large/Small values are median synchronized wall milliseconds per decode step.
Reduction and 95% bootstrap intervals use paired mean ratios, which need not equal
ratios of the displayed medians. Forty shuffled pairs were collected per cell.

| Batch | Context | Large ms | Small ms | Paired mean reduction | 95% interval |
|---:|---:|---:|---:|---:|---:|
| 1 | 128 | 54.85 | 54.39 | 0.82% | 0.70–0.94% |
| 8 | 128 | 55.84 | 55.22 | 1.03% | 0.93–1.12% |
| 16 | 128 | 55.77 | 55.20 | 0.97% | 0.87–1.06% |
| 32 | 128 | 56.96 | 56.25 | 1.24% | 1.17–1.32% |
| 64 | 128 | 56.89 | 56.23 | 1.11% | 1.01–1.22% |
| 1 | 2048 | 56.48 | 55.98 | 0.70% | 0.37–0.92% |
| 8 | 2048 | 57.11 | 56.46 | 1.12% | 1.04–1.20% |
| 16 | 2048 | 57.38 | 56.69 | 1.18% | 1.00–1.32% |
| 32 | 2048 | 60.11 | 59.22 | 1.36% | 1.25–1.46% |
| 64 | 2048 | 74.14 | 71.65 | 5.62% | 3.12–10.06% |

**Final-cell caveat:** one Large sample took 148.40 ms, approximately twice normal,
and inflates the mean result. All observations are retained. The medians indicate
**3.36% typical savings**, supported by essentially the same CUDA-event difference.
No cell establishes the predeclared approximately 10% planning screen; that screen
is an investment criterion, not a universal threshold for useful serving gains.

Job 6092263 supplied nine completed cells before cancellation. Job 6092480 completed
only batch 64/context 2048 (exit 0, 26:40). The original JSON correctly retains its
incomplete-grid status; the combined summary contains all ten cells. No completed
cell reported OOM.

## Bottleneck profile

Context 2,048; three captures per configuration. Values are median **active GPU
operation durations**, excluding gaps. Attention includes projections, cache
updates, transformations, and attention kernels. These are not decode latencies.

| Batch | Width | FFN ms | Attention/cache ms | Other ms |
|---:|---|---:|---:|---:|
| 1 | Large | 10.21 | 3.83 | 7.69 |
| 1 | Small | 7.46 | 3.83 | 7.68 |
| 64 | Large | 11.78 | 38.68 | 10.04 |
| 64 | Small | 8.52 | 38.41 | 9.88 |

- **Narrowing works:** FFN GPU time falls approximately 27–28%. Small halves width
  in 20 of 35 layers, reducing nominal FFN projection work by approximately 29%.
  Unchanged-layer FFN time remains approximately stable.
- **Batch 1:** FFNs are 47% of Large's active GPU time, but both widths still launch
  5,370 kernels. Profiled gaps occupy approximately 80% of the Large timeline.
  Profiling inflates gaps: this is not an estimate of production overhead. The
  evidence points to eager execution and dispatch costs masking GPU-work savings.
- **Batch 64:** attention/cache work is 64% of Large's active GPU time. A
  representative trace includes 13.78 ms of attention copies and 6.46 ms of
  concatenation; 13.43 ms of copies sit beneath reshape → clone → copy. KV-head
  expansion is a plausible source, but was not proved with shapes or Python stacks.

Successful profiling job 6092969 completed with exit 0 in 5:18. All twelve traces
contain 35 FFN and 35 attention CPU scopes. Independent external-ID kernel
attribution matches profiler totals within 0.000001 ms, with no unmapped GPU
activities. A failed pilot caused by counting both CPU and GPU annotations is
excluded. The first startup capture in the successful run was discarded.

## Interpretation and limits

Keep the current eager serving-integration plan stopped. The profile supplies a
specific reason to consider a bounded runtime experiment targeting launch overhead
and attention/KV copies. Compilation, fusion, graph replay, or a compatible serving
backend are candidates, not measured improvements. Stronger clean timing must
precede quality evaluation and adaptive-versus-request-level serving comparisons.

Prefill and width application are excluded; each cache is prepared at its decode
width. There is no quality, mixed-width-transition, continuous-batching, SLO-goodput,
or bandwidth-counter evaluation. Intervals and traces describe within-job samples.
Profiling changes latency and overlap. Three diagnostic unprofiled pairs with
annotations enabled gave 60.70/60.01 ms at batch 1 and 88.28/88.09 ms at batch 64;
these differ from the clean benchmark and do not replace it. Clocks were guarded
but not locked or continuously sampled.

The pinned checkpoint is `af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee`; the environment
used PyTorch 2.9.1+cu128 and Transformers 5.7.0. Patched Large matched original probe
logits exactly. Historical raw results are unchanged, including original paths.

## Files and reproduction

- `code/`: timing/profiling runners, analysis, required worker/harness helpers,
  published presets, and one PACE launcher. No dependency on other Week 2 folders.
- `results/timing/`: two original runs, logs, and combined CSV.
- `results/profile/`: successful run, log, CSV, independent attribution audit, and
  twelve losslessly compressed traces. Decompress a `.trace.json.gz` to view it.
- `source_manifest.json`: source origins, hashes, and exact packaging edits.

From this folder, using Python 3.10+ (analysis needs only the standard library):

```sh
python3 code/analyze_timing.py results/timing/job-6092263.json --additional results/timing/job-6092480.json
python3 code/analyze_profile.py results/profile/job-6092969.json
python3 code/audit_profiles.py results/profile/job-6092969.json
```

To rerun on PACE, upload this folder and use the existing cached-model environment:

```sh
sbatch --export=ALL,STUDY_ROOT="$PWD",STUDY_MODE=profile --output=results/profile/job-%j.log code/run_pace.sbatch
sbatch --export=ALL,STUDY_ROOT="$PWD",STUDY_MODE=timing --output=results/timing/job-%j.log code/run_pace.sbatch
```

The timing launcher defaults to the ten-cell grid. Pass `--batches` and `--contexts`
to bound it. The profile is fixed to batches 1/64 and context 2,048. No new GPU runs
were performed while packaging.
