# Measured results: FFN width switching on one L40S

Contract: TTFT <= 1.0 s and max ITL <= 0.2 s per request (secondary mean TPOT <= 0.1 s); goodput = SLO-satisfying completed requests / wall time.

## 0. Instrument gates (run on the same GPU before the matrix)

Source: `results/gates/job-6106532.json`, level `full`, overall **PASS**; clock guard `True` (1950.0 MHz SM).

| gate | verdict | evidence |
|---|---|---|
| `switchable_equals_static` | pass | dynamic width path is bit-identical to the static workers |
| `batch_equivalence` | pass | batched tokens equal per-row tokens |
| `batch_equivalence` | pass | batched tokens equal per-row tokens |
| `injected_delay` | pass | all-forward injection moved median max-ITL 9.9 ms (expect ~10 ms); decode-only injection moved it 4.9 ms, diluted because each request's largest gap is usually the prefill iteration |
| `null_diff` | pass | identical schedules; spread 0.2% TTFT / 0.2% ITL over 2 runs |

### Width sensitivity measured through the loop's own forwards

Median GPU ms per forward from `calibrate.py --mode measure` (reps=5, device=cuda).

| prefill chunk (tokens) | large ms | small ms | small/large | saving |
|---:|---:|---:|---:|---:|
| 128 | 58.10 | 56.93 | 0.980 | 2.0% |
| 256 | 57.58 | 57.16 | 0.993 | 0.7% |
| 512 | 59.59 | 58.53 | 0.982 | 1.8% |
| 1024 | 77.62 | 68.24 | 0.879 | 12.1% |
| 2048 | 151.58 | 127.07 | 0.838 | 16.2% |
| 4096 | 354.16 | 305.97 | 0.864 | 13.6% |

| decode batch | large ms | small ms | small/large |
|---:|---:|---:|---:|
| 1 | 56.02 | 55.70 | 0.994 |
| 8 | 56.50 | 56.75 | 1.004 |
| 16 | 56.65 | 56.51 | 0.997 |
| 32 | 58.24 | 57.92 | 0.994 |
| 64 | 58.31 | 58.05 | 0.996 |

Switch apply cost: **0.117 ms** for all 35 layers, plus a 0.60 ms boundary allowance.

### Capacity and the frozen load ladder

Measured service capacity **3.23 req/s** (0.309 GPU s per request), split **27% prefill / 73% decode** of GPU seconds.

| trace | mean req/s | requests | span s | mean prompt | mean output |
|---|---:|---:|---:|---:|---:|

Ladder (`--rate-scale` on the steady window, whose own mean rate is 5.50 req/s): underloaded **0.29**, saturated **0.53**, overloaded **0.76**, backlog-inducing **1.18**.

### How much of each workload is prefill? (the lever's addressable share)

Prefill GPU seconds = prompt tokens x measured prefill cost; decode GPU seconds = output tokens / measured batch-64 decode rate. This is the ceiling the phase hybrid can act on: it changes prefill cost only.

| trace | requests | mean prompt | mean output | prefill GPU s | decode GPU s | prefill share | best-case saving if prefill ran Small |
|---|---:|---:|---:|---:|---:|---:|---:|
| azure_code_burst | 632 | 2101 | 26 | 98.3 | 15.2 | 0.87 | 14.0% |
| azure_code_mixshift | 931 | 2027 | 26 | 139.7 | 22.0 | 0.86 | 14.0% |
| azure_code_steady | 414 | 2223 | 27 | 68.1 | 10.3 | 0.87 | 14.1% |
| azure_conv_burst | 1408 | 1422 | 127 | 148.2 | 162.4 | 0.48 | 7.7% |
| azure_conv_mixshift | 1274 | 1138 | 150 | 107.3 | 173.9 | 0.38 | 6.2% |
| azure_conv_steady | 989 | 1117 | 249 | 81.8 | 224.1 | 0.27 | 4.3% |


### Cells (declared before the runs)

| cell | trace | rate-scale | x capacity | requests | truncated window |
|---|---|---:|---:|---:|---|
| steady2-control_mid | azure_conv_steady.json | 0.2 | 0.34 | 150 | yes |
| steady-underloaded | azure_conv_steady.json | 0.294 | 0.5 | 220 | yes |
| code-overloaded | azure_code_steady.json | 1.64 | 1.3 | 220 | yes |
| steady2-control_low | azure_conv_steady.json | 0.1 | 0.17 | 150 | yes |
| burst-saturated | azure_conv_burst.json | 0.371 | 0.9 | 220 | yes |
| mixshift-overloaded | azure_conv_mixshift.json | 0.594 | 1.3 | 220 | yes |
| steady-saturated | azure_conv_steady.json | 0.529 | 0.9 | 220 | yes |
| burst2-backlog | azure_conv_burst.json | 0.825 | 2.0 | 220 | yes |
| steady-overloaded | azure_conv_steady.json | 0.764 | 1.3 | 220 | yes |

Truncation comes from `--max-run-seconds 300.0` applied identically to every policy so that a cell fits a bounded slice of the allocation.


## 1. Validation (checked before anything is analyzed)

| run | trace | rate | policy | rep | requests | iters | wall s | accounting | validated |
|---|---|---|---|---|---:|---:|---:|---|---|
| measured-cell-burst-saturated | azure_conv_burst | 0.371 | static_large | 0 | 220 | 845 | 119.9 | pass | pass |
| measured-cell-burst-saturated | azure_conv_burst | 0.371 | static_small | 0 | 220 | 861 | 116.1 | pass | pass |
| measured-cell-burst-saturated | azure_conv_burst | 0.371 | phase_hybrid | 0 | 220 | 859 | 117.2 | pass | pass |
| measured-cell-burst2-backlog | azure_conv_burst | 0.825 | static_large | 0 | 220 | 823 | 118.8 | pass | pass |
| measured-cell-burst2-backlog | azure_conv_burst | 0.825 | static_small | 0 | 220 | 823 | 114.1 | pass | pass |
| measured-cell-burst2-backlog | azure_conv_burst | 0.825 | phase_hybrid | 0 | 220 | 823 | 115.3 | pass | pass |
| measured-cell-burst3-control_mid | azure_conv_burst | 0.14 | static_large | 0 | 150 | 2199 | 162.6 | pass | pass |
| measured-cell-burst3-control_mid | azure_conv_burst | 0.14 | static_small | 0 | 150 | 2239 | 162.3 | pass | pass |
| measured-cell-burst3-control_mid | azure_conv_burst | 0.14 | phase_hybrid | 0 | 150 | 2224 | 162.5 | pass | pass |
| measured-cell-code-overloaded | azure_code_steady | 1.64 | static_large | 0 | 220 | 671 | 89.4 | pass | pass |
| measured-cell-code-overloaded | azure_code_steady | 1.64 | static_small | 0 | 220 | 671 | 83.4 | pass | pass |
| measured-cell-code-overloaded | azure_code_steady | 1.64 | phase_hybrid | 0 | 220 | 671 | 83.9 | pass | pass |
| measured-cell-mixshift-overloaded | azure_conv_mixshift | 0.594 | static_large | 0 | 220 | 920 | 128.9 | pass | pass |
| measured-cell-mixshift-overloaded | azure_conv_mixshift | 0.594 | static_small | 0 | 220 | 924 | 124.2 | pass | pass |
| measured-cell-mixshift-overloaded | azure_conv_mixshift | 0.594 | phase_hybrid | 0 | 220 | 923 | 125.6 | pass | pass |
| measured-cell-steady-overloaded | azure_conv_steady | 0.764 | static_large | 0 | 220 | 1559 | 189.1 | pass | pass |
| measured-cell-steady-overloaded | azure_conv_steady | 0.764 | static_small | 0 | 220 | 1563 | 185.1 | pass | pass |
| measured-cell-steady-overloaded | azure_conv_steady | 0.764 | phase_hybrid | 0 | 220 | 1562 | 188.2 | pass | pass |
| measured-cell-steady-saturated | azure_conv_steady | 0.529 | static_large | 0 | 220 | 1599 | 191.7 | pass | pass |
| measured-cell-steady-saturated | azure_conv_steady | 0.529 | static_small | 0 | 220 | 1604 | 187.1 | pass | pass |
| measured-cell-steady-saturated | azure_conv_steady | 0.529 | phase_hybrid | 0 | 220 | 1601 | 197.5 | pass | pass |
| measured-cell-steady-underloaded | azure_conv_steady | 0.294 | static_large | 0 | 220 | 1786 | 197.8 | pass | pass |
| measured-cell-steady-underloaded | azure_conv_steady | 0.294 | static_small | 0 | 220 | 1826 | 194.2 | pass | pass |
| measured-cell-steady-underloaded | azure_conv_steady | 0.294 | phase_hybrid | 0 | 220 | 1803 | 199.0 | pass | pass |
| measured-cell-steady2-control_low | azure_conv_steady | 0.1 | static_large | 0 | 150 | 4569 | 306.6 | pass | pass |
| measured-cell-steady2-control_low | azure_conv_steady | 0.1 | static_small | 0 | 150 | 4624 | 308.3 | pass | pass |
| measured-cell-steady2-control_low | azure_conv_steady | 0.1 | phase_hybrid | 0 | 150 | 4639 | 306.4 | pass | pass |
| measured-cell-steady2-control_mid | azure_conv_steady | 0.2 | static_large | 0 | 150 | 2088 | 170.3 | pass | pass |
| measured-cell-steady2-control_mid | azure_conv_steady | 0.2 | static_small | 0 | 150 | 2127 | 169.6 | pass | pass |
| measured-cell-steady2-control_mid | azure_conv_steady | 0.2 | phase_hybrid | 0 | 150 | 2103 | 169.9 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | static_large | 0 | 150 | 4568 | 306.6 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | static_small | 0 | 150 | 4624 | 306.3 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | phase_hybrid | 0 | 150 | 4423 | 306.6 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | static_small | 1 | 150 | 4580 | 306.4 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | phase_hybrid | 1 | 150 | 4543 | 308.1 | pass | pass |
| measured-cell-steady4-control_low | azure_conv_steady | 0.1 | static_large | 1 | 150 | 4563 | 306.6 | pass | pass |

## 2. Per-cell results (mean over repetitions)

`queueing` applies the contract's overload signals to what actually happened, not to the requested rate-scale: queue-active iterations > 0.5, or TTFT p50 more than twice the unloaded TTFT for the same length mix (taken from the trace's own lightest run when that run is genuinely unloaded, otherwise from the measured prefill cost of its median prompt -- a trace measured at one load level has no unloaded run of its own).

Attainment failures are split three ways by the contract: TTFT only, ITL only, or both. `fail both` is a TTFT failure *and* an ITL failure, not a leftover.

`fail ITL` and `fail both` are the contract's buckets. `ITL over gate (attributable)` counts requests in *any* bucket whose largest gap exceeded the gate but stayed under 0.4 s -- longer than any prefill chunk measured here -- so it excludes host stalls (a single stall fails every concurrent request at once) and is the schedule-attributable part of the ITL signal.

| trace | rate | policy | attainment | goodput/s | throughput/s | fail TTFT | fail ITL | ITL over gate (attributable) | fail both | TTFT p50 | TTFT p99 | ITL p95 | queueing |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| azure_code_steady | 1.64 | phase_hybrid | 0.000 | 0.000 | 2.62 | 1 | 7 | 219 | 212 | 22044 | 36269 | 320 | queueing |
| azure_code_steady | 1.64 | static_large | 0.000 | 0.000 | 2.46 | 1 | 7 | 219 | 212 | 24953 | 41753 | 345 | queueing |
| azure_code_steady | 1.64 | static_small | 0.000 | 0.000 | 2.64 | 1 | 7 | 218 | 212 | 21873 | 35885 | 317 | queueing |
| azure_conv_burst | 0.14 | phase_hybrid | 0.267 | 0.249 | 0.92 | 0 | 110 | 110 | 0 | 118 | 625 | 253 | no queue |
| azure_conv_burst | 0.14 | static_large | 0.153 | 0.144 | 0.92 | 0 | 127 | 127 | 0 | 114 | 704 | 280 | no queue |
| azure_conv_burst | 0.14 | static_small | 0.340 | 0.295 | 0.92 | 0 | 99 | 99 | 0 | 118 | 615 | 247 | no queue |
| azure_conv_burst | 0.371 | phase_hybrid | 0.000 | 0.000 | 1.88 | 0 | 84 | 196 | 136 | 2371 | 15926 | 407 | queueing |
| azure_conv_burst | 0.371 | static_large | 0.000 | 0.000 | 1.83 | 0 | 70 | 189 | 150 | 3464 | 18768 | 433 | queueing |
| azure_conv_burst | 0.371 | static_small | 0.000 | 0.000 | 1.89 | 0 | 85 | 203 | 135 | 1988 | 15040 | 403 | queueing |
| azure_conv_burst | 0.825 | phase_hybrid | 0.000 | 0.000 | 1.91 | 0 | 6 | 192 | 214 | 21994 | 55435 | 413 | queueing |
| azure_conv_burst | 0.825 | static_large | 0.000 | 0.000 | 1.85 | 0 | 4 | 187 | 216 | 23756 | 58804 | 437 | queueing |
| azure_conv_burst | 0.825 | static_small | 0.000 | 0.000 | 1.93 | 0 | 6 | 196 | 214 | 21743 | 54482 | 404 | queueing |
| azure_conv_mixshift | 0.594 | phase_hybrid | 0.000 | 0.000 | 1.75 | 0 | 52 | 197 | 168 | 14029 | 49861 | 406 | queueing |
| azure_conv_mixshift | 0.594 | static_large | 0.000 | 0.000 | 1.71 | 0 | 45 | 193 | 175 | 15344 | 52787 | 433 | queueing |
| azure_conv_mixshift | 0.594 | static_small | 0.000 | 0.000 | 1.77 | 0 | 53 | 200 | 167 | 13636 | 48909 | 403 | queueing |
| azure_conv_steady | 0.1 | phase_hybrid | 0.629 | 0.297 | 0.49 | 1 | 54 | 42 | 1 | 110 | 1500 | 1523 | no queue |
| azure_conv_steady | 0.1 | static_large | 0.516 | 0.254 | 0.49 | 0 | 73 | 73 | 0 | 113 | 567 | 233 | no queue |
| azure_conv_steady | 0.1 | static_small | 0.676 | 0.324 | 0.49 | 0 | 48 | 43 | 1 | 107 | 676 | 625 | no queue |
| azure_conv_steady | 0.2 | phase_hybrid | 0.260 | 0.219 | 0.88 | 0 | 111 | 111 | 0 | 115 | 638 | 243 | no queue |
| azure_conv_steady | 0.2 | static_large | 0.233 | 0.206 | 0.88 | 0 | 115 | 115 | 0 | 128 | 712 | 260 | no queue |
| azure_conv_steady | 0.2 | static_small | 0.313 | 0.244 | 0.88 | 0 | 103 | 103 | 0 | 122 | 644 | 239 | no queue |
| azure_conv_steady | 0.294 | phase_hybrid | 0.032 | 0.011 | 1.11 | 0 | 120 | 181 | 93 | 351 | 20052 | 1041 | queueing |
| azure_conv_steady | 0.294 | static_large | 0.027 | 0.016 | 1.11 | 0 | 110 | 210 | 104 | 637 | 21505 | 364 | queueing |
| azure_conv_steady | 0.294 | static_small | 0.045 | 0.027 | 1.13 | 0 | 126 | 209 | 84 | 278 | 18483 | 344 | queueing |
| azure_conv_steady | 0.529 | phase_hybrid | 0.018 | 0.000 | 1.11 | 0 | 53 | 154 | 163 | 25787 | 81317 | 4053 | queueing |
| azure_conv_steady | 0.529 | static_large | 0.014 | 0.000 | 1.15 | 0 | 53 | 212 | 164 | 26211 | 75608 | 372 | queueing |
| azure_conv_steady | 0.529 | static_small | 0.018 | 0.000 | 1.18 | 0 | 53 | 215 | 163 | 24487 | 71819 | 367 | queueing |
| azure_conv_steady | 0.764 | phase_hybrid | 0.009 | 0.000 | 1.17 | 0 | 44 | 215 | 174 | 36884 | 94538 | 355 | queueing |
| azure_conv_steady | 0.764 | static_large | 0.005 | 0.000 | 1.16 | 0 | 46 | 218 | 173 | 37500 | 95726 | 360 | queueing |
| azure_conv_steady | 0.764 | static_small | 0.005 | 0.000 | 1.19 | 0 | 50 | 219 | 169 | 35913 | 92071 | 350 | queueing |

### 2b. Mechanism: where the latency actually goes

`slow iterations` are iterations longer than the frozen ITL gate; a long prompt is prefilled in 2048-token chunks inside a decode iteration, so those iterations delay every concurrently running request.

| trace | rate | policy | prefill token share | prefill iter time share | mean iter ms | max iter ms | mean prefill-iter ms | slow iters | stalls >0.4s | worst iter ms | queue active | TTFT p50 x unloaded | peak running | switches |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| azure_code_steady | 1.64 | phase_hybrid | 0.99 | 0.78 | 125 | 257 | 179 | 154 | 0 | 257 | 0.54 | 116.52x | 48 | 727 |
| azure_code_steady | 1.64 | static_large | 0.99 | 0.80 | 133 | 266 | 195 | 183 | 0 | 266 | 0.54 | 131.90x | 48 | 0 |
| azure_code_steady | 1.64 | static_small | 0.99 | 0.78 | 124 | 317 | 178 | 151 | 0 | 317 | 0.54 | 115.62x | 48 | 1 |
| azure_conv_burst | 0.14 | phase_hybrid | 0.92 | 0.19 | 73 | 213 | 154 | 26 | 0 | 213 | 0.06 | 1.04x | 18 | 391 |
| azure_conv_burst | 0.14 | static_large | 0.92 | 0.20 | 74 | 238 | 165 | 72 | 0 | 238 | 0.06 | 1.00x | 18 | 0 |
| azure_conv_burst | 0.14 | static_small | 0.92 | 0.19 | 72 | 212 | 153 | 21 | 0 | 212 | 0.06 | 1.04x | 18 | 1 |
| azure_conv_burst | 0.371 | phase_hybrid | 0.93 | 0.54 | 136 | 371 | 217 | 164 | 0 | 371 | 0.47 | 20.87x | 48 | 581 |
| azure_conv_burst | 0.371 | static_large | 0.93 | 0.56 | 142 | 393 | 228 | 199 | 0 | 393 | 0.50 | 30.50x | 48 | 0 |
| azure_conv_burst | 0.371 | static_small | 0.93 | 0.54 | 134 | 369 | 214 | 142 | 0 | 369 | 0.46 | 17.50x | 48 | 1 |
| azure_conv_burst | 0.825 | phase_hybrid | 0.93 | 0.56 | 140 | 376 | 218 | 162 | 0 | 376 | 0.57 | 193.64x | 48 | 581 |
| azure_conv_burst | 0.825 | static_large | 0.93 | 0.57 | 144 | 316 | 230 | 193 | 0 | 316 | 0.57 | 209.15x | 48 | 0 |
| azure_conv_burst | 0.825 | static_small | 0.93 | 0.56 | 138 | 374 | 217 | 151 | 0 | 374 | 0.57 | 191.43x | 48 | 1 |
| azure_conv_mixshift | 0.594 | phase_hybrid | 0.92 | 0.50 | 136 | 380 | 219 | 152 | 0 | 380 | 0.56 | 154.34x | 48 | 565 |
| azure_conv_mixshift | 0.594 | static_large | 0.92 | 0.51 | 140 | 398 | 231 | 190 | 0 | 398 | 0.56 | 168.80x | 48 | 0 |
| azure_conv_mixshift | 0.594 | static_small | 0.92 | 0.50 | 134 | 366 | 218 | 142 | 0 | 366 | 0.56 | 150.02x | 48 | 1 |
| azure_conv_steady | 0.1 | phase_hybrid | 0.79 | 0.08 | 68 | 1928 | 146 | 10 | 4 | 1928 | 0.03 | 1.00x | 16 | 319 |
| azure_conv_steady | 0.1 | static_large | 0.79 | 0.08 | 67 | 234 | 149 | 21 | 0 | 234 | 0.03 | 1.02x | 16 | 0 |
| azure_conv_steady | 0.1 | static_small | 0.79 | 0.08 | 66 | 636 | 145 | 7 | 1 | 636 | 0.03 | 0.96x | 16 | 1 |
| azure_conv_steady | 0.2 | phase_hybrid | 0.79 | 0.15 | 81 | 226 | 154 | 16 | 0 | 226 | 0.07 | 1.04x | 30 | 319 |
| azure_conv_steady | 0.2 | static_large | 0.79 | 0.15 | 81 | 260 | 163 | 21 | 0 | 260 | 0.07 | 1.15x | 30 | 0 |
| azure_conv_steady | 0.2 | static_small | 0.79 | 0.14 | 80 | 224 | 153 | 16 | 0 | 224 | 0.06 | 1.10x | 30 | 1 |
| azure_conv_steady | 0.294 | phase_hybrid | 0.79 | 0.22 | 110 | 1040 | 190 | 89 | 2 | 1040 | 0.36 | 3.16x | 48 | 467 |
| azure_conv_steady | 0.294 | static_large | 0.79 | 0.24 | 111 | 338 | 198 | 104 | 0 | 338 | 0.39 | 5.75x | 48 | 0 |
| azure_conv_steady | 0.294 | static_small | 0.79 | 0.22 | 106 | 340 | 185 | 75 | 0 | 340 | 0.34 | 2.51x | 48 | 1 |
| azure_conv_steady | 0.529 | phase_hybrid | 0.79 | 0.26 | 123 | 4052 | 214 | 106 | 3 | 4052 | 0.61 | 232.64x | 48 | 467 |
| azure_conv_steady | 0.529 | static_large | 0.79 | 0.25 | 120 | 372 | 204 | 116 | 0 | 372 | 0.61 | 236.47x | 48 | 0 |
| azure_conv_steady | 0.529 | static_small | 0.79 | 0.24 | 116 | 366 | 192 | 96 | 0 | 366 | 0.61 | 220.91x | 48 | 1 |
| azure_conv_steady | 0.764 | phase_hybrid | 0.79 | 0.25 | 120 | 322 | 197 | 105 | 0 | 322 | 0.65 | 332.75x | 48 | 467 |
| azure_conv_steady | 0.764 | static_large | 0.79 | 0.25 | 121 | 301 | 204 | 120 | 0 | 301 | 0.65 | 338.30x | 48 | 0 |
| azure_conv_steady | 0.764 | static_small | 0.79 | 0.25 | 118 | 334 | 194 | 100 | 0 | 334 | 0.65 | 323.98x | 48 | 1 |

## 3. Paired per-request comparisons

Requests are matched by id, so both policies served the same prompt and the same arrival. `only A / only B` are the discordant attainment pairs (exact McNemar p).


### static_small vs static_large

| trace | rate | rep | n | attain A | attain B | Δ | only A | only B | McNemar p | TTFT delta mean ms | 95% CI | d goodput/s | d throughput/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| azure_code_steady | 1.64 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -2696.3 | [-2916.8, -2475.9] | +0.000 | +7.1% |
| azure_conv_burst | 0.14 | 0 | 150 | 0.340 | 0.153 | +0.187 | 28 | 0 | 7.45e-09 | -18.7 | [-25.5, -12.2] | +0.151 | +0.2% |
| azure_conv_burst | 0.371 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -1450.1 | [-1612.6, -1289.6] | +0.000 | +3.3% |
| azure_conv_burst | 0.825 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -2104.9 | [-2264.8, -1943.7] | +0.000 | +4.1% |
| azure_conv_mixshift | 0.594 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -1817.4 | [-2004.4, -1631.1] | +0.000 | +3.7% |
| azure_conv_steady | 0.1 | 0 | 150 | 0.633 | 0.520 | +0.113 | 24 | 7 | 0.00333 | 16.2 | [-4.3, 43.9] | +0.042 | -0.5% |
| azure_conv_steady | 0.1 | 0 | 150 | 0.707 | 0.520 | +0.187 | 28 | 0 | 7.45e-09 | -19.1 | [-24.0, -14.4] | +0.081 | +0.1% |
| azure_conv_steady | 0.1 | 1 | 150 | 0.687 | 0.507 | +0.180 | 27 | 0 | 1.49e-08 | -11.9 | [-18.0, -6.2] | +0.088 | +0.1% |
| azure_conv_steady | 0.2 | 0 | 150 | 0.313 | 0.233 | +0.080 | 12 | 0 | 0.000488 | -14.1 | [-19.7, -8.7] | +0.039 | +0.4% |
| azure_conv_steady | 0.294 | 0 | 220 | 0.045 | 0.027 | +0.018 | 4 | 0 | 0.125 | -1223.5 | [-1409.8, -1043.5] | +0.011 | +1.9% |
| azure_conv_steady | 0.529 | 0 | 220 | 0.018 | 0.014 | +0.005 | 1 | 0 | 1 | -1726.2 | [-1901.9, -1551.6] | +0.000 | +2.5% |
| azure_conv_steady | 0.764 | 0 | 220 | 0.005 | 0.005 | +0.000 | 0 | 0 | 1 | -1552.3 | [-1701.2, -1401.2] | +0.000 | +2.2% |

### phase_hybrid vs static_large

| trace | rate | rep | n | attain A | attain B | Δ | only A | only B | McNemar p | TTFT delta mean ms | 95% CI | d goodput/s | d throughput/s |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|
| azure_code_steady | 1.64 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -2548.0 | [-2756.6, -2339.6] | +0.000 | +6.6% |
| azure_conv_burst | 0.14 | 0 | 150 | 0.267 | 0.153 | +0.113 | 17 | 0 | 1.53e-05 | -17.1 | [-23.7, -10.8] | +0.105 | +0.1% |
| azure_conv_burst | 0.371 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -1064.6 | [-1184.9, -947.1] | +0.000 | +2.4% |
| azure_conv_burst | 0.825 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -1744.6 | [-1864.6, -1622.2] | +0.000 | +3.0% |
| azure_conv_mixshift | 0.594 | 0 | 220 | 0.000 | 0.000 | +0.000 | 0 | 0 | 1 | -1361.1 | [-1498.5, -1224.4] | +0.000 | +2.6% |
| azure_conv_steady | 0.1 | 0 | 150 | 0.693 | 0.520 | +0.173 | 28 | 2 | 8.68e-07 | -8.9 | [-13.5, -4.3] | +0.074 | +0.0% |
| azure_conv_steady | 0.1 | 0 | 150 | 0.560 | 0.520 | +0.040 | 22 | 16 | 0.418 | 52.4 | [4.8, 112.6] | +0.007 | +0.0% |
| azure_conv_steady | 0.1 | 1 | 150 | 0.633 | 0.507 | +0.127 | 25 | 6 | 0.000878 | 22.1 | [-11.9, 70.1] | +0.049 | -0.5% |
| azure_conv_steady | 0.2 | 0 | 150 | 0.260 | 0.233 | +0.027 | 4 | 0 | 0.125 | -17.7 | [-23.5, -12.1] | +0.013 | +0.3% |
| azure_conv_steady | 0.294 | 0 | 220 | 0.032 | 0.027 | +0.005 | 2 | 1 | 1 | -525.3 | [-602.4, -450.0] | -0.005 | -0.6% |
| azure_conv_steady | 0.529 | 0 | 220 | 0.018 | 0.014 | +0.005 | 1 | 0 | 1 | 897.4 | [599.5, 1219.0] | +0.000 | -3.0% |
| azure_conv_steady | 0.764 | 0 | 220 | 0.009 | 0.005 | +0.005 | 1 | 0 | 1 | -545.7 | [-599.8, -491.5] | +0.000 | +0.5% |

## 4. SLO sensitivity (attainment recomputed from stored latencies)

| trace | rate | policy | rep | TTFT 0.5 s / ITL 0.1 s | TTFT 0.5 s / ITL 0.2 s | TTFT 1.0 s / ITL 0.1 s | TTFT 1.0 s / ITL 0.2 s | TTFT 2.0 s / ITL 0.1 s | TTFT 2.0 s / ITL 0.2 s |
|---|---:|---|---:|---:|---:|---:|---:|---:|---:|
| azure_code_steady | 1.64 | phase_hybrid | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_code_steady | 1.64 | static_large | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_code_steady | 1.64 | static_small | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.14 | phase_hybrid | 0 | 0.000 | 0.247 | 0.000 | 0.267 | 0.000 | 0.267 |
| azure_conv_burst | 0.14 | static_large | 0 | 0.000 | 0.140 | 0.000 | 0.153 | 0.000 | 0.153 |
| azure_conv_burst | 0.14 | static_small | 0 | 0.000 | 0.320 | 0.000 | 0.340 | 0.000 | 0.340 |
| azure_conv_burst | 0.371 | phase_hybrid | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.371 | static_large | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.371 | static_small | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.825 | phase_hybrid | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.825 | static_large | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_burst | 0.825 | static_small | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_mixshift | 0.594 | phase_hybrid | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_mixshift | 0.594 | static_large | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_mixshift | 0.594 | static_small | 0 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| azure_conv_steady | 0.1 | phase_hybrid | 0 | 0.000 | 0.553 | 0.000 | 0.560 | 0.000 | 0.567 |
| azure_conv_steady | 0.1 | phase_hybrid | 1 | 0.000 | 0.627 | 0.000 | 0.633 | 0.000 | 0.633 |
| azure_conv_steady | 0.1 | static_large | 0 | 0.000 | 0.493 | 0.000 | 0.520 | 0.000 | 0.520 |
| azure_conv_steady | 0.1 | static_large | 1 | 0.000 | 0.480 | 0.000 | 0.507 | 0.000 | 0.507 |
| azure_conv_steady | 0.1 | static_small | 0 | 0.000 | 0.700 | 0.000 | 0.707 | 0.000 | 0.707 |
| azure_conv_steady | 0.1 | static_small | 1 | 0.000 | 0.680 | 0.000 | 0.687 | 0.000 | 0.687 |
| azure_conv_steady | 0.2 | phase_hybrid | 0 | 0.000 | 0.253 | 0.000 | 0.260 | 0.000 | 0.260 |
| azure_conv_steady | 0.2 | static_large | 0 | 0.000 | 0.227 | 0.000 | 0.233 | 0.000 | 0.233 |
| azure_conv_steady | 0.2 | static_small | 0 | 0.000 | 0.307 | 0.000 | 0.313 | 0.000 | 0.313 |
| azure_conv_steady | 0.294 | phase_hybrid | 0 | 0.000 | 0.032 | 0.000 | 0.032 | 0.000 | 0.032 |
| azure_conv_steady | 0.294 | static_large | 0 | 0.000 | 0.027 | 0.000 | 0.027 | 0.000 | 0.027 |
| azure_conv_steady | 0.294 | static_small | 0 | 0.000 | 0.045 | 0.000 | 0.045 | 0.000 | 0.045 |
| azure_conv_steady | 0.529 | phase_hybrid | 0 | 0.000 | 0.018 | 0.000 | 0.018 | 0.000 | 0.018 |
| azure_conv_steady | 0.529 | static_large | 0 | 0.000 | 0.014 | 0.000 | 0.014 | 0.000 | 0.014 |
| azure_conv_steady | 0.529 | static_small | 0 | 0.000 | 0.018 | 0.000 | 0.018 | 0.000 | 0.018 |
| azure_conv_steady | 0.764 | phase_hybrid | 0 | 0.000 | 0.009 | 0.000 | 0.009 | 0.000 | 0.009 |
| azure_conv_steady | 0.764 | static_large | 0 | 0.000 | 0.005 | 0.000 | 0.005 | 0.000 | 0.005 |
| azure_conv_steady | 0.764 | static_small | 0 | 0.000 | 0.005 | 0.000 | 0.005 | 0.000 | 0.005 |
