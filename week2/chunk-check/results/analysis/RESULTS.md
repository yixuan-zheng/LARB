# Final prefill chunk comparison

Three repetitions per configuration, 150 identical trace requests per run,
rate scale 0.1; TTFT <= 1 s and max token gap <= 200 ms. All stalls retained.
All figures are latency-only; answer quality is not evaluated.

| Configuration | Attainment per run | Mean attainment | Mean on-time req/s | Mean throughput req/s | TTFT p50, ms |
|---|---|---:|---:|---:|---:|
| large_original | 54.0%, 48.7%, 50.0% | 50.9% | 0.251 | 0.490 | 114.5 |
| hybrid_original | 57.3%, 70.7%, 73.3% | 67.1% | 0.319 | 0.489 | 105.6 |
| large_chunk512 | 95.3%, 72.7%, 96.7% | 88.2% | 0.428 | 0.489 | 237.6 |
| hybrid_chunk512 | 76.7%, 96.7%, 92.0% | 88.4% | 0.427 | 0.489 | 234.0 |

| Comparison | Attainment difference per repetition |
|---|---|
| hybrid_original minus large_original | +3.3 pp, +22.0 pp, +23.3 pp |
| large_chunk512 minus large_original | +41.3 pp, +24.0 pp, +46.7 pp |
| hybrid_chunk512 minus large_chunk512 | -18.7 pp, +24.0 pp, -4.7 pp |

These within-allocation repetitions do not establish across-day uncertainty.
Token differences are diagnostics, not scored quality failures. Chunking may change
BF16 numerical paths and therefore generated answers. This remains one model, one
GPU, one low-load trace and the padded-cache eager harness. Raw request and
iteration records are retained; 0.4-second stalls are counted, never removed.
