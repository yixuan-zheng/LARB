# FFN width latency profile

Generated from `results/latency_profile.json` by `report_latency.py`. Every ratio
in the paired tables is a *paired* mean ratio over shuffled, interleaved samples;
`verdict` follows the pre-registered rule (bootstrap CI excludes 1.0 **and**
|median delta| > 2%). Sections are ordered so the answer comes before its
evidence; `Provenance` maps every block back to the record it came from.

## Verdicts at a glance

Each row is the short answer the rest of the report substantiates; `see` names
the section that carries the evidence. Width ratios are the `gpu_ms` metric
(the `wall_ms` rows in `results/comparisons.csv` track it to a few tenths of a
percent).

| question | measured | verdict | see |
| --- | --- | --- | --- |
| Instrument resolves a known effect (S0) | 3 gating checks | pass | instrument gate |
| Batch-1 decode speedup vs width | ratio 0.9912-0.9976 | within_noise | utilization |
| Batched decode speedup vs width | ratio 0.9892-0.9991 | within_noise | utilization |
| Prefill speedup vs width | ratio 0.8235-0.9947 | appreciable in 8/12 | utilization |
| Backend choice vs width (eager/compile) | ratio 0.8052-0.9131 | appreciable in 4/4 | utilization |
| End-to-end inter-token latency vs width (S4) | ratio 0.9839-1.0017 | cross-process, within_noise | end-to-end |
| Ceiling if dispatch were free (S6) | 1.074-1.169x | analytic bound | attribution |
| Resident weights Large minus Small (S7) | 1.88 GiB total, 1.88 GiB of it FFN | exact | memory |
| Dynamic per-iteration switching (S8-S11) | s10_switch_iteration, s11_switch_flexibility, s8_switch_mechanism, s9_switch_phase | measured | dynamic switching |

## Instrument gate (s0)

S0 proves the harness resolves a real effect and invents none; every other
number is read in the units it establishes.

| file | all checks passed | # checks | checks | clock ok |
| --- | --- | --- | --- | --- |
| s0_harness_validation__all__local.json | True | 3 | gemv_scaling, known_2x_compute, null_diff | True |

## Coverage

One row per scenario that ran, with the number of rows it contributed to each
table. A scenario showing `none` is present in the record set but produced
nothing renderable -- a reporting gap, not evidence of absence.

| scenario | records | rendered rows | tables filled |
| --- | --- | --- | --- |
| s0_harness_validation | 1 | 15 | comparisons 3, gates 1, utilization 11 |
| s10_switch_iteration | 1 | 1 | switching 1 |
| s11_switch_flexibility | 1 | 1 | switching 1 |
| s1_decode_step | 2 | 29 | comparisons 16, utilization 13 |
| s2_prefill | 1 | 42 | comparisons 24, utilization 18 |
| s3_batch_decode | 2 | 70 | comparisons 40, utilization 30 |
| s4_end_to_end | 3 | 20 | end_to_end 12, end_to_end_ratios 8 |
| s5_backends | 1 | 10 | comparisons 4, utilization 6 |
| s6_layer_profile | 3 | 12 | attribution 12 |
| s7_memory_roofline | 3 | 9 | memory 3, utilization 6 |
| s8_switch_mechanism | 1 | 39 | switching 1, utilization 38 |
| s9_switch_phase | 1 | 1 | switching 1 |

| field | value |
| --- | --- |
| records | 20 |
| completed records | 20 |
| utilization rows | 122 |
| comparison rows | 87 |
| end-to-end rows | 12 |
| s6 attribution rows | 12 |
| s7 memory rows | 3 |
| appreciable effects | 21 |
| MDD floor | 0.10% |
| residual harness bias | 0.90% |

## Utilization per configuration

`run` distinguishes rows that share a config but came from different files
(for example the `session` and `smoke` S1 runs). Full table:
`results/latency_profile.csv`.

| scenario | config | run | preset | gpu ms | alpha ms | BW GB/s | BW % peak | MFU % | tok/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0_harness_validation | a | local | unknown | 0.110 | 0.023 | - | - | - | - |
| s0_harness_validation | b | local | unknown | 0.109 | 0.023 | - | - | - | - |
| s0_harness_validation | big | local | unknown | 2.603 | 0.025 | - | - | - | - |
| s0_harness_validation | flush_off | local | unknown | 0.186 | 0.025 | - | - | - | - |
| s0_harness_validation | flush_on | local | unknown | 0.186 | 0.026 | - | - | - | - |
| s0_harness_validation | n16384 | local | unknown | 0.185 | 0.025 | - | - | - | - |
| s0_harness_validation | n32768 | local | unknown | 0.287 | 0.026 | - | - | - | - |
| s0_harness_validation | n4096 | local | unknown | 0.075 | 0.025 | - | - | - | - |
| s0_harness_validation | n65536 | local | unknown | 0.490 | 0.026 | - | - | - | - |
| s0_harness_validation | n8192 | local | unknown | 0.114 | 0.025 | - | - | - | - |
| s0_harness_validation | small | local | small | 1.169 | 0.025 | - | - | - | - |
| s1_decode_step | large_L128 | session | large | 55.051 | 0.033 | 267.8 | 31.0 | 0.039 | 18.2 |
| s1_decode_step | large_L128 | smoke | large | 54.597 | 0.034 | 270.1 | 31.3 | 0.039 | 18.3 |
| s1_decode_step | large_L2048 | session | large | 56.628 | 0.031 | 260.4 | 30.1 | 0.039 | 17.7 |
| s1_decode_step | large_L512 | session | large | 56.543 | 0.031 | 260.8 | 30.2 | 0.038 | 17.7 |
| s1_decode_step | large_L512 | smoke | large | 56.500 | 0.032 | 261.0 | 30.2 | 0.038 | 17.7 |
| s1_decode_step | medium_L128 | session | medium | 54.751 | 0.034 | 250.9 | 29.0 | 0.034 | 18.3 |
| s1_decode_step | medium_L2048 | session | medium | 56.562 | 0.031 | 242.9 | 28.1 | 0.034 | 17.7 |
| s1_decode_step | medium_L512 | session | medium | 56.332 | 0.033 | 243.9 | 28.2 | 0.034 | 17.8 |
| s1_decode_step | small_L128 | session | small | 54.675 | 0.035 | 232.9 | 27.0 | 0.029 | 18.3 |
| s1_decode_step | small_L128 | smoke | small | 54.136 | 0.034 | 235.2 | 27.2 | 0.029 | 18.5 |
| s1_decode_step | small_L2048 | session | small | 56.230 | 0.031 | 226.4 | 26.2 | 0.029 | 17.8 |
| s1_decode_step | small_L512 | session | small | 56.196 | 0.032 | 226.6 | 26.2 | 0.029 | 17.8 |
| s1_decode_step | small_L512 | smoke | small | 55.967 | 0.033 | 227.5 | 26.3 | 0.029 | 17.9 |
| s2_prefill | large_L128_B1 | session | large | 57.931 | 0.030 | 254.5 | 29.5 | 4.721 | 2209.5 |
| s2_prefill | large_L128_B4 | session | large | 58.646 | 0.031 | 251.4 | 29.1 | 18.654 | 8730.3 |
| s2_prefill | large_L2048_B1 | session | large | 160.077 | 0.032 | 92.1 | 10.7 | 27.842 | 12793.8 |
| s2_prefill | large_L2048_B4 | session | large | 810.975 | 0.042 | 18.2 | 2.1 | 21.983 | 10101.4 |
| s2_prefill | large_L512_B1 | session | large | 61.530 | 0.031 | 239.6 | 27.7 | 17.907 | 8321.2 |
| s2_prefill | large_L512_B4 | session | large | 148.381 | 0.032 | 99.4 | 11.5 | 29.702 | 13802.3 |
| s2_prefill | medium_L128_B1 | session | medium | 57.543 | 0.030 | 238.8 | 27.6 | 4.135 | 2224.4 |
| s2_prefill | medium_L128_B4 | session | medium | 57.960 | 0.031 | 237.0 | 27.4 | 16.419 | 8833.6 |
| s2_prefill | medium_L2048_B1 | session | medium | 146.519 | 0.032 | 93.8 | 10.9 | 26.533 | 13977.8 |
| s2_prefill | medium_L2048_B4 | session | medium | 761.467 | 0.042 | 18.0 | 2.1 | 20.421 | 10758.2 |
| s2_prefill | medium_L512_B1 | session | medium | 60.929 | 0.032 | 225.5 | 26.1 | 15.747 | 8403.2 |
| s2_prefill | medium_L512_B4 | session | medium | 135.184 | 0.033 | 101.6 | 11.8 | 28.389 | 15149.7 |
| s2_prefill | small_L128_B1 | session | small | 57.202 | 0.031 | 222.6 | 25.8 | 3.537 | 2237.7 |
| s2_prefill | small_L128_B4 | session | small | 57.271 | 0.031 | 222.3 | 25.7 | 14.131 | 8939.9 |
| s2_prefill | small_L2048_B1 | session | small | 133.305 | 0.032 | 95.5 | 11.1 | 24.891 | 15363.2 |
| s2_prefill | small_L2048_B4 | session | small | 710.980 | 0.041 | 17.9 | 2.1 | 18.668 | 11522.1 |
| s2_prefill | small_L512_B1 | session | small | 60.185 | 0.031 | 211.5 | 24.5 | 13.576 | 8507.1 |
| s2_prefill | small_L512_B4 | session | small | 122.202 | 0.032 | 104.2 | 12.1 | 26.745 | 16759.1 |
| s3_batch_decode | large_L128_B1 | session | large | 54.260 | 0.033 | 271.8 | 31.5 | 0.039 | 18.4 |
| s3_batch_decode | large_L128_B16 | s3b | large | 56.676 | 0.036 | 261.6 | 30.3 | 0.605 | 282.3 |
| s3_batch_decode | large_L128_B4 | session | large | 55.193 | 0.032 | 267.5 | 31.0 | 0.155 | 72.5 |
| s3_batch_decode | large_L128_B8 | s3b | large | 55.693 | 0.031 | 265.5 | 30.7 | 0.308 | 143.6 |
| s3_batch_decode | large_L1_B1 | session | large | 54.411 | 0.038 | 271.0 | 31.4 | 0.039 | 18.4 |
| s3_batch_decode | large_L1_B16 | s3b | large | 55.556 | 0.035 | 265.4 | 30.7 | 0.614 | 288.0 |
| s3_batch_decode | large_L1_B4 | session | large | 55.636 | 0.038 | 265.0 | 30.7 | 0.153 | 71.9 |
| s3_batch_decode | large_L1_B8 | s3b | large | 55.376 | 0.033 | 266.3 | 30.8 | 0.308 | 144.5 |
| s3_batch_decode | large_L2048_B1 | session | large | 56.132 | 0.032 | 263.2 | 30.5 | 0.039 | 17.8 |
| s3_batch_decode | large_L2048_B4 | session | large | 58.285 | 0.038 | 254.9 | 29.5 | 0.151 | 68.6 |
| s3_batch_decode | medium_L128_B1 | session | medium | 53.823 | 0.033 | 255.4 | 29.6 | 0.035 | 18.6 |
| s3_batch_decode | medium_L128_B16 | s3b | medium | 56.525 | 0.033 | 244.5 | 28.3 | 0.528 | 283.1 |
| s3_batch_decode | medium_L128_B4 | session | medium | 55.158 | 0.034 | 249.5 | 28.9 | 0.135 | 72.5 |
| s3_batch_decode | medium_L128_B8 | s3b | medium | 55.344 | 0.031 | 249.0 | 28.8 | 0.269 | 144.6 |
| s3_batch_decode | medium_L1_B1 | session | medium | 54.263 | 0.039 | 253.2 | 29.3 | 0.034 | 18.4 |
| s3_batch_decode | medium_L1_B16 | s3b | medium | 55.124 | 0.033 | 249.2 | 28.8 | 0.538 | 290.3 |
| s3_batch_decode | medium_L1_B4 | session | medium | 55.396 | 0.039 | 248.0 | 28.7 | 0.134 | 72.2 |
| s3_batch_decode | medium_L1_B8 | s3b | medium | 55.121 | 0.034 | 249.2 | 28.8 | 0.269 | 145.1 |
| s3_batch_decode | medium_L2048_B1 | session | medium | 56.006 | 0.032 | 245.8 | 28.4 | 0.034 | 17.9 |
| s3_batch_decode | medium_L2048_B4 | session | medium | 57.866 | 0.037 | 239.3 | 27.7 | 0.133 | 69.1 |
| s3_batch_decode | small_L128_B1 | session | small | 53.733 | 0.034 | 237.0 | 27.4 | 0.030 | 18.6 |
| s3_batch_decode | small_L128_B16 | s3b | small | 55.965 | 0.034 | 229.0 | 26.5 | 0.453 | 285.9 |
| s3_batch_decode | small_L128_B4 | session | small | 54.709 | 0.034 | 233.1 | 27.0 | 0.116 | 73.1 |
| s3_batch_decode | small_L128_B8 | s3b | small | 55.139 | 0.032 | 231.7 | 26.8 | 0.230 | 145.1 |
| s3_batch_decode | small_L1_B1 | session | small | 54.138 | 0.037 | 235.2 | 27.2 | 0.029 | 18.5 |
| s3_batch_decode | small_L1_B16 | s3b | small | 54.934 | 0.032 | 231.8 | 26.8 | 0.459 | 291.3 |
| s3_batch_decode | small_L1_B4 | session | small | 55.176 | 0.040 | 230.8 | 26.7 | 0.114 | 72.5 |
| s3_batch_decode | small_L1_B8 | s3b | small | 54.840 | 0.032 | 232.2 | 26.9 | 0.230 | 145.9 |
| s3_batch_decode | small_L2048_B1 | session | small | 55.712 | 0.031 | 229.0 | 26.5 | 0.029 | 17.9 |
| s3_batch_decode | small_L2048_B4 | session | small | 57.717 | 0.035 | 222.5 | 25.8 | 0.114 | 69.3 |
| s5_backends | large_compile | session | large | 114.799 | 0.034 | 128.4 | 14.9 | 38.390 | 17839.9 |
| s5_backends | large_eager | session | large | 150.521 | 0.034 | 98.0 | 11.3 | 29.279 | 13606.1 |
| s5_backends | medium_compile | session | medium | 103.306 | 0.034 | 133.0 | 15.4 | 37.149 | 19824.6 |
| s5_backends | medium_eager | session | medium | 137.666 | 0.032 | 99.8 | 11.6 | 27.877 | 14876.6 |
| s5_backends | small_compile | session | small | 92.347 | 0.034 | 137.9 | 16.0 | 35.392 | 22177.1 |
| s5_backends | small_eager | session | small | 124.059 | 0.033 | 102.6 | 11.9 | 26.345 | 16508.3 |
| s7_memory_roofline | decode | session | unknown | 57.272 | 0.031 | - | - | - | - |
| s7_memory_roofline | decode | session | unknown | 57.062 | 0.032 | - | - | - | - |
| s7_memory_roofline | decode | session | unknown | 56.613 | 0.031 | - | - | - | - |
| s7_memory_roofline | prefill | session | unknown | 150.098 | 0.032 | - | - | - | - |
| s7_memory_roofline | prefill | session | unknown | 138.363 | 0.032 | - | - | - | - |
| s7_memory_roofline | prefill | session | unknown | 122.835 | 0.032 | - | - | - | - |
| s8_switch_mechanism | cold_large | session | large | 151.908 | 0.032 | - | - | - | - |
| s8_switch_mechanism | cold_medium | session | medium | 138.855 | 0.032 | - | - | - | - |
| s8_switch_mechanism | cold_small | session | small | 125.235 | 0.031 | - | - | - | - |
| s8_switch_mechanism | dyn_large | session | large | 149.863 | 0.035 | - | - | - | - |
| s8_switch_mechanism | dyn_large | session | large | 58.464 | 0.033 | - | - | - | - |
| s8_switch_mechanism | dyn_large | session | large | 149.260 | 0.033 | - | - | - | - |
| s8_switch_mechanism | dyn_large | session | large | 58.558 | 0.032 | - | - | - | - |
| s8_switch_mechanism | dyn_medium | session | medium | 136.374 | 0.035 | - | - | - | - |
| s8_switch_mechanism | dyn_medium | session | medium | 58.617 | 0.032 | - | - | - | - |
| s8_switch_mechanism | dyn_medium | session | medium | 135.642 | 0.033 | - | - | - | - |
| s8_switch_mechanism | dyn_medium | session | medium | 58.506 | 0.033 | - | - | - | - |
| s8_switch_mechanism | dyn_small | session | small | 122.699 | 0.035 | - | - | - | - |
| s8_switch_mechanism | dyn_small | session | small | 58.639 | 0.032 | - | - | - | - |
| s8_switch_mechanism | dyn_small | session | small | 121.872 | 0.032 | - | - | - | - |
| s8_switch_mechanism | dyn_small | session | small | 58.318 | 0.033 | - | - | - | - |
| s8_switch_mechanism | null_a | session | unknown | 122.845 | 0.034 | - | - | - | - |
| s8_switch_mechanism | null_a | session | unknown | 58.697 | 0.032 | - | - | - | - |
| s8_switch_mechanism | null_a | session | unknown | 122.028 | 0.032 | - | - | - | - |
| s8_switch_mechanism | null_a | session | unknown | 58.455 | 0.032 | - | - | - | - |
| s8_switch_mechanism | null_b | session | unknown | 123.002 | 0.035 | - | - | - | - |
| s8_switch_mechanism | null_b | session | unknown | 58.713 | 0.033 | - | - | - | - |
| s8_switch_mechanism | null_b | session | unknown | 122.179 | 0.032 | - | - | - | - |
| s8_switch_mechanism | null_b | session | unknown | 58.555 | 0.032 | - | - | - | - |
| s8_switch_mechanism | static_medium | session | medium | 136.856 | 0.035 | - | - | - | - |
| s8_switch_mechanism | static_medium | session | medium | 59.280 | 0.032 | - | - | - | - |
| s8_switch_mechanism | static_medium | session | medium | 136.057 | 0.033 | - | - | - | - |
| s8_switch_mechanism | static_medium | session | medium | 59.370 | 0.033 | - | - | - | - |
| s8_switch_mechanism | static_small | session | small | 123.421 | 0.036 | - | - | - | - |
| s8_switch_mechanism | static_small | session | small | 58.983 | 0.033 | - | - | - | - |
| s8_switch_mechanism | static_small | session | small | 122.580 | 0.033 | - | - | - | - |
| s8_switch_mechanism | static_small | session | small | 58.956 | 0.032 | - | - | - | - |
| s8_switch_mechanism | stock_large | session | large | 150.173 | 0.035 | - | - | - | - |
| s8_switch_mechanism | stock_large | session | large | 59.105 | 0.033 | - | - | - | - |
| s8_switch_mechanism | stock_large | session | large | 149.622 | 0.033 | - | - | - | - |
| s8_switch_mechanism | stock_large | session | large | 59.292 | 0.033 | - | - | - | - |
| s8_switch_mechanism | warm_large | session | large | 152.336 | 0.032 | - | - | - | - |
| s8_switch_mechanism | warm_medium | session | medium | 138.994 | 0.032 | - | - | - | - |
| s8_switch_mechanism | warm_small | session | small | 124.873 | 0.032 | - | - | - | - |

## Large vs Small (paired)

In-process, interleaved, so the pairing cancels slow clock/thermal drift.
`run` distinguishes rows that share a grid and metric but came from different
files. Full table: `results/comparisons.csv`.

| scenario | grid | metric | run | speedup | ratio 95% CI | MDD | median delta | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0_harness_validation | known_2x_compute | wall_ms | local | 2.1716 | [0.4558, 0.4663] | 0.31% | -54.51% | appreciable |
| s0_harness_validation | l2_flush_probe | wall_ms | local | 0.9969 | [0.9983, 1.0091] | 0.54% | -0.08% | within_noise |
| s0_harness_validation | null_diff | wall_ms | local | 1.0091 | [0.9760, 1.0028] | 1.40% | -0.54% | within_noise |
| s1_decode_step | L128 | gpu_ms | session | 1.0079 | [0.9892, 0.9955] | 0.32% | -0.68% | within_noise |
| s1_decode_step | L128 | gpu_ms | session | 1.0050 | [0.9914, 0.9988] | 0.38% | -0.54% | within_noise |
| s1_decode_step | L128 | gpu_ms | smoke | 1.0057 | [0.9898, 0.9994] | 0.51% | -0.84% | within_noise |
| s1_decode_step | L128 | wall_ms | session | 1.0078 | [0.9893, 0.9956] | 0.32% | -0.68% | within_noise |
| s1_decode_step | L128 | wall_ms | session | 1.0050 | [0.9914, 0.9989] | 0.38% | -0.54% | within_noise |
| s1_decode_step | L128 | wall_ms | smoke | 1.0057 | [0.9898, 0.9995] | 0.51% | -0.84% | within_noise |
| s1_decode_step | L2048 | gpu_ms | session | 1.0084 | [0.9886, 0.9945] | 0.31% | -0.70% | within_noise |
| s1_decode_step | L2048 | gpu_ms | session | 1.0024 | [0.9955, 0.9999] | 0.23% | -0.12% | within_noise |
| s1_decode_step | L2048 | wall_ms | session | 1.0084 | [0.9886, 0.9945] | 0.31% | -0.70% | within_noise |
| s1_decode_step | L2048 | wall_ms | session | 1.0024 | [0.9955, 0.9999] | 0.23% | -0.12% | within_noise |
| s1_decode_step | L512 | gpu_ms | session | 1.0066 | [0.9912, 0.9954] | 0.22% | -0.61% | within_noise |
| s1_decode_step | L512 | gpu_ms | session | 1.0031 | [0.9942, 0.9997] | 0.29% | -0.37% | within_noise |
| s1_decode_step | L512 | gpu_ms | smoke | 1.0088 | [0.9868, 0.9951] | 0.44% | -0.94% | within_noise |
| s1_decode_step | L512 | wall_ms | session | 1.0066 | [0.9913, 0.9955] | 0.22% | -0.61% | within_noise |
| s1_decode_step | L512 | wall_ms | session | 1.0030 | [0.9942, 0.9997] | 0.29% | -0.37% | within_noise |
| s1_decode_step | L512 | wall_ms | smoke | 1.0088 | [0.9868, 0.9951] | 0.44% | -0.94% | within_noise |
| s2_prefill | L128_B1 | gpu_ms | session | 1.0131 | [0.9830, 0.9909] | 0.43% | -1.26% | within_noise |
| s2_prefill | L128_B1 | gpu_ms | session | 1.0053 | [0.9899, 0.9994] | 0.50% | -0.67% | within_noise |
| s2_prefill | L128_B1 | wall_ms | session | 1.0130 | [0.9831, 0.9910] | 0.42% | -1.26% | within_noise |
| s2_prefill | L128_B1 | wall_ms | session | 1.0053 | [0.9898, 0.9994] | 0.50% | -0.67% | within_noise |
| s2_prefill | L128_B4 | gpu_ms | session | 1.0275 | [0.9629, 0.9796] | 1.00% | -2.34% | appreciable |
| s2_prefill | L128_B4 | gpu_ms | session | 1.0161 | [0.9759, 0.9892] | 0.80% | -1.17% | within_noise |
| s2_prefill | L128_B4 | wall_ms | session | 1.0275 | [0.9629, 0.9797] | 1.00% | -2.34% | appreciable |
| s2_prefill | L128_B4 | wall_ms | session | 1.0161 | [0.9759, 0.9892] | 0.80% | -1.17% | within_noise |
| s2_prefill | L2048_B1 | gpu_ms | session | 1.2017 | [0.8305, 0.8340] | 0.19% | -16.72% | appreciable |
| s2_prefill | L2048_B1 | gpu_ms | session | 1.0916 | [0.9140, 0.9187] | 0.26% | -8.47% | appreciable |
| s2_prefill | L2048_B1 | wall_ms | session | 1.2016 | [0.8305, 0.8340] | 0.19% | -16.72% | appreciable |
| s2_prefill | L2048_B1 | wall_ms | session | 1.0916 | [0.9140, 0.9187] | 0.26% | -8.47% | appreciable |
| s2_prefill | L2048_B4 | gpu_ms | session | 1.1414 | [0.8753, 0.8769] | 0.10% | -12.33% | appreciable |
| s2_prefill | L2048_B4 | gpu_ms | session | 1.0660 | [0.9370, 0.9392] | 0.12% | -6.10% | appreciable |
| s2_prefill | L2048_B4 | wall_ms | session | 1.1414 | [0.8753, 0.8769] | 0.10% | -12.33% | appreciable |
| s2_prefill | L2048_B4 | wall_ms | session | 1.0660 | [0.9370, 0.9392] | 0.12% | -6.10% | appreciable |
| s2_prefill | L512_B1 | gpu_ms | session | 1.0209 | [0.9756, 0.9835] | 0.41% | -2.19% | appreciable |
| s2_prefill | L512_B1 | gpu_ms | session | 1.0098 | [0.9879, 0.9933] | 0.29% | -0.98% | within_noise |
| s2_prefill | L512_B1 | wall_ms | session | 1.0209 | [0.9756, 0.9835] | 0.41% | -2.18% | appreciable |
| s2_prefill | L512_B1 | wall_ms | session | 1.0098 | [0.9879, 0.9933] | 0.29% | -0.97% | within_noise |
| s2_prefill | L512_B4 | gpu_ms | session | 1.2144 | [0.8209, 0.8259] | 0.29% | -17.64% | appreciable |
| s2_prefill | L512_B4 | gpu_ms | session | 1.0980 | [0.9085, 0.9131] | 0.25% | -8.89% | appreciable |
| s2_prefill | L512_B4 | wall_ms | session | 1.2143 | [0.8209, 0.8259] | 0.30% | -17.64% | appreciable |
| s2_prefill | L512_B4 | wall_ms | session | 1.0979 | [0.9085, 0.9131] | 0.25% | -8.89% | appreciable |
| s3_batch_decode | L128_B1 | gpu_ms | session | 1.0095 | [0.9870, 0.9944] | 0.39% | -0.97% | within_noise |
| s3_batch_decode | L128_B1 | gpu_ms | session | 1.0063 | [0.9891, 0.9983] | 0.49% | -0.81% | within_noise |
| s3_batch_decode | L128_B1 | wall_ms | session | 1.0095 | [0.9870, 0.9944] | 0.40% | -0.98% | within_noise |
| s3_batch_decode | L128_B1 | wall_ms | session | 1.0063 | [0.9891, 0.9983] | 0.49% | -0.81% | within_noise |
| s3_batch_decode | L128_B16 | gpu_ms | s3b | 1.0096 | [0.9826, 0.9974] | 0.80% | -1.26% | within_noise |
| s3_batch_decode | L128_B16 | gpu_ms | s3b | 1.0039 | [0.9920, 1.0002] | 0.44% | -0.27% | within_noise |
| s3_batch_decode | L128_B16 | wall_ms | s3b | 1.0096 | [0.9825, 0.9974] | 0.80% | -1.26% | within_noise |
| s3_batch_decode | L128_B16 | wall_ms | s3b | 1.0039 | [0.9919, 1.0001] | 0.44% | -0.27% | within_noise |
| s3_batch_decode | L128_B4 | gpu_ms | session | 1.0078 | [0.9874, 0.9977] | 0.56% | -0.88% | within_noise |
| s3_batch_decode | L128_B4 | gpu_ms | session | 1.0009 | [0.9944, 1.0039] | 0.50% | -0.06% | within_noise |
| s3_batch_decode | L128_B4 | wall_ms | session | 1.0078 | [0.9874, 0.9978] | 0.56% | -0.87% | within_noise |
| s3_batch_decode | L128_B4 | wall_ms | session | 1.0008 | [0.9945, 1.0039] | 0.50% | -0.06% | within_noise |
| s3_batch_decode | L128_B8 | gpu_ms | s3b | 1.0089 | [0.9883, 0.9938] | 0.29% | -0.99% | within_noise |
| s3_batch_decode | L128_B8 | gpu_ms | s3b | 1.0067 | [0.9919, 0.9949] | 0.16% | -0.63% | within_noise |
| s3_batch_decode | L128_B8 | wall_ms | s3b | 1.0088 | [0.9883, 0.9938] | 0.29% | -0.99% | within_noise |
| s3_batch_decode | L128_B8 | wall_ms | s3b | 1.0067 | [0.9920, 0.9949] | 0.16% | -0.62% | within_noise |
| s3_batch_decode | L1_B1 | gpu_ms | session | 1.0058 | [0.9924, 0.9964] | 0.21% | -0.50% | within_noise |
| s3_batch_decode | L1_B1 | gpu_ms | session | 1.0036 | [0.9949, 0.9980] | 0.17% | -0.27% | within_noise |
| s3_batch_decode | L1_B1 | wall_ms | session | 1.0057 | [0.9924, 0.9964] | 0.21% | -0.50% | within_noise |
| s3_batch_decode | L1_B1 | wall_ms | session | 1.0036 | [0.9949, 0.9980] | 0.17% | -0.27% | within_noise |
| s3_batch_decode | L1_B16 | gpu_ms | s3b | 1.0109 | [0.9860, 0.9926] | 0.35% | -1.12% | within_noise |
| s3_batch_decode | L1_B16 | gpu_ms | s3b | 1.0059 | [0.9914, 0.9971] | 0.31% | -0.78% | within_noise |
| s3_batch_decode | L1_B16 | wall_ms | s3b | 1.0109 | [0.9860, 0.9926] | 0.35% | -1.12% | within_noise |
| s3_batch_decode | L1_B16 | wall_ms | s3b | 1.0059 | [0.9913, 0.9971] | 0.31% | -0.78% | within_noise |
| s3_batch_decode | L1_B4 | gpu_ms | session | 1.0073 | [0.9903, 0.9958] | 0.29% | -0.83% | within_noise |
| s3_batch_decode | L1_B4 | gpu_ms | session | 1.0037 | [0.9950, 0.9976] | 0.13% | -0.43% | within_noise |
| s3_batch_decode | L1_B4 | wall_ms | session | 1.0072 | [0.9903, 0.9958] | 0.29% | -0.83% | within_noise |
| s3_batch_decode | L1_B4 | wall_ms | session | 1.0037 | [0.9950, 0.9976] | 0.13% | -0.43% | within_noise |
| s3_batch_decode | L1_B8 | gpu_ms | s3b | 1.0106 | [0.9867, 0.9927] | 0.32% | -0.97% | within_noise |
| s3_batch_decode | L1_B8 | gpu_ms | s3b | 1.0049 | [0.9932, 0.9970] | 0.21% | -0.46% | within_noise |
| s3_batch_decode | L1_B8 | wall_ms | s3b | 1.0105 | [0.9867, 0.9928] | 0.32% | -0.97% | within_noise |
| s3_batch_decode | L1_B8 | wall_ms | s3b | 1.0049 | [0.9932, 0.9970] | 0.21% | -0.46% | within_noise |
| s3_batch_decode | L2048_B1 | gpu_ms | session | 1.0075 | [0.9892, 0.9967] | 0.41% | -0.75% | within_noise |
| s3_batch_decode | L2048_B1 | gpu_ms | session | 1.0015 | [0.9940, 1.0030] | 0.48% | -0.23% | within_noise |
| s3_batch_decode | L2048_B1 | wall_ms | session | 1.0075 | [0.9892, 0.9967] | 0.41% | -0.75% | within_noise |
| s3_batch_decode | L2048_B1 | wall_ms | session | 1.0015 | [0.9940, 1.0030] | 0.48% | -0.22% | within_noise |
| s3_batch_decode | L2048_B4 | gpu_ms | session | 1.0100 | [0.9850, 0.9950] | 0.54% | -0.98% | within_noise |
| s3_batch_decode | L2048_B4 | gpu_ms | session | 1.0055 | [0.9893, 1.0009] | 0.62% | -0.72% | within_noise |
| s3_batch_decode | L2048_B4 | wall_ms | session | 1.0100 | [0.9850, 0.9950] | 0.54% | -0.97% | within_noise |
| s3_batch_decode | L2048_B4 | wall_ms | session | 1.0054 | [0.9893, 1.0009] | 0.62% | -0.72% | within_noise |
| s5_backends | compile | gpu_ms | session | 1.2419 | [0.7993, 0.8112] | 0.69% | -19.56% | appreciable |
| s5_backends | compile | gpu_ms | session | 1.1088 | [0.8956, 0.9081] | 0.68% | -10.01% | appreciable |
| s5_backends | eager | gpu_ms | session | 1.2160 | [0.8193, 0.8254] | 0.36% | -17.58% | appreciable |
| s5_backends | eager | gpu_ms | session | 1.0951 | [0.9094, 0.9168] | 0.41% | -8.54% | appreciable |

## End-to-end generation (s4)

TTFT, inter-token latency, whole-request time and throughput -- the numbers a
reader would actually quote. Per-config rows: `results/s4_end_to_end.csv`.

| preset | grid | batch | prompt | new tok | TTFT p50 ms | TTFT p90 ms | ITL p50 ms | ITL p90 ms | e2e p50 ms | decode tok/s | e2e tok/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| large | L1024_B1 | 1 | 1024 | 96 | 135.4 | 135.5 | 56.02 | 56.49 | 5464 | 17.8 | 17.6 |
| medium | L1024_B1 | 1 | 1024 | 96 | 130.3 | 130.3 | 55.64 | 56.04 | 5421 | 18.0 | 17.7 |
| small | L1024_B1 | 1 | 1024 | 96 | 125.8 | 125.9 | 55.42 | 56.01 | 5399 | 18.0 | 17.8 |
| large | L1024_B8 | 8 | 1024 | 96 | 840.2 | 840.3 | 57.34 | 57.72 | 6294 | 139.5 | 122.0 |
| medium | L1024_B8 | 8 | 1024 | 96 | 788.9 | 789.3 | 56.94 | 57.75 | 6210 | 140.5 | 123.7 |
| small | L1024_B8 | 8 | 1024 | 96 | 738.5 | 738.5 | 56.42 | 57.02 | 6105 | 141.8 | 125.8 |
| large | L128_B1 | 1 | 128 | 96 | 113.3 | 114.5 | 53.93 | 54.42 | 5243 | 18.5 | 18.3 |
| medium | L128_B1 | 1 | 128 | 96 | 114.5 | 115.4 | 54.16 | 54.69 | 5253 | 18.5 | 18.3 |
| small | L128_B1 | 1 | 128 | 96 | 113.2 | 114.1 | 53.58 | 54.15 | 5207 | 18.7 | 18.4 |
| large | L128_B8 | 8 | 128 | 96 | 131.5 | 131.7 | 55.57 | 55.85 | 5413 | 144.0 | 141.9 |
| medium | L128_B8 | 8 | 128 | 96 | 126.4 | 126.4 | 55.12 | 55.79 | 5374 | 145.1 | 142.9 |
| small | L128_B8 | 8 | 128 | 96 | 121.5 | 121.6 | 54.81 | 55.16 | 5332 | 146.0 | 144.0 |

_source: `s4_end_to_end__large__session.json`, `s4_end_to_end__medium__session.json`, `s4_end_to_end__small__session.json`_

### Width ratio from the per-step samples (cross-process)

S4 runs one preset per process, so this ratio joins the same grid across the
three files instead of using the interleaved in-process pairing the other
scenarios use. The bootstrap still pairs step indices, but the samples were
not collected interleaved: read it as corroboration, not as a pre-registered
verdict. Rows: `results/s4_end_to_end_ratios.csv`.

| grid | vs large | n | ratio | ratio 95% CI | MDD | median delta | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| L1024_B1 | medium | 190 | 0.9928 | [0.9926, 0.9931] | 0.03% | -0.69% | within_noise |
| L1024_B1 | small | 190 | 0.9896 | [0.9895, 0.9897] | 0.01% | -1.07% | within_noise |
| L1024_B8 | medium | 190 | 0.9939 | [0.9936, 0.9943] | 0.03% | -0.69% | within_noise |
| L1024_B8 | small | 190 | 0.9839 | [0.9837, 0.9842] | 0.03% | -1.61% | within_noise |
| L128_B1 | medium | 190 | 1.0017 | [1.0012, 1.0023] | 0.06% | 0.43% | within_noise |
| L128_B1 | small | 190 | 0.9932 | [0.9929, 0.9934] | 0.03% | -0.65% | within_noise |
| L128_B8 | medium | 190 | 0.9935 | [0.9932, 0.9939] | 0.04% | -0.80% | within_noise |
| L128_B8 | small | 190 | 0.9865 | [0.9862, 0.9868] | 0.03% | -1.36% | within_noise |

## Where the step time goes, and the ceiling (s6)

`FFN % step` divides by the timed step (which the event hooks inflate);
`FFN % attributed` divides by the summed timed modules (now including AltUp).
`in scope` is the attributed FFN share times the ~28.6% of FFN weights a slice
removes, and `ceiling` is the speedup if that in-scope portion became free. It
is a bound at *this* grid -- S6's own large-vs-small prefill step ratio sits
inside the large preset's ceiling. Grids with a lighter attention load carry a
larger FFN share (hence a higher ceiling), so a ratio measured elsewhere
(S2/S5) can sit slightly above this grid's bound.

| regime | preset | step ms | FFN ms | FFN % step | FFN % attributed | width cut % | in scope % | ceiling x |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| decode | large | 75.8 | 15.4 | 20.4 | 29.8 | 28.6 | 8.5 | 1.093 |
| decode | medium | 76.7 | 13.9 | 18.1 | 26.7 | 28.6 | 7.6 | 1.083 |
| decode | small | 74.8 | 12.2 | 16.4 | 24.0 | 28.6 | 6.9 | 1.074 |
| prefill | large | 785.6 | 331.0 | 42.1 | 50.6 | 28.6 | 14.4 | 1.169 |
| prefill | medium | 732.9 | 281.2 | 38.4 | 46.6 | 28.6 | 13.3 | 1.154 |
| prefill | small | 681.2 | 231.6 | 34.0 | 42.0 | 28.6 | 12.0 | 1.136 |

Per-module decode time share:

| preset | altup % | laurel % | mlp % | norm % | per_layer_input % | per_layer_projection % | self_attn % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| large | 13.8 | 6.3 | 20.4 | 3.8 | 1.7 | 1.3 | 21.1 |
| medium | 15.5 | 6.3 | 18.1 | 3.8 | 1.7 | 1.4 | 21.1 |
| small | 17.1 | 6.4 | 16.4 | 3.9 | 1.7 | 1.4 | 21.3 |

Per-module prefill time share:

| preset | altup % | laurel % | mlp % | norm % | per_layer_input % | per_layer_projection % | self_attn % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| large | 22.4 | 3.7 | 42.1 | 3.0 | 0.2 | 0.3 | 11.6 |
| medium | 24.1 | 4.0 | 38.4 | 3.0 | 0.2 | 0.3 | 12.3 |
| small | 25.8 | 4.2 | 34.0 | 3.2 | 0.3 | 0.3 | 13.2 |

### Kernel-category view (independent of the module view)

From a `torch.profiler` CUDA-activity pass. The matmul share is a second,
independent estimate of what a width change can touch; a module-level FFN
share that disagrees with the matmul share is itself a finding.

| regime | preset | cuda ms | copy % | elementwise % | matmul % | other % | reduction % |
| --- | --- | --- | --- | --- | --- | --- | --- |
| decode | large | 95.0 | 7.2 | 3.3 | 18.3 | 64.3 | 6.9 |
| decode | medium | 89.2 | 7.8 | 3.5 | 17.8 | 63.5 | 7.3 |
| decode | small | 83.2 | 8.4 | 3.8 | 17.3 | 62.7 | 7.8 |
| prefill | large | 2910.9 | 8.4 | 7.1 | 15.2 | 60.4 | 8.9 |
| prefill | medium | 2654.5 | 9.1 | 7.7 | 14.7 | 59.4 | 9.1 |
| prefill | small | 2440.1 | 9.9 | 8.3 | 14.2 | 58.5 | 9.2 |

_source: `s6_layer_profile__large__session.json`, `s6_layer_profile__medium__session.json`, `s6_layer_profile__small__session.json`_

## Memory, capacity and roofline (s7)

The memory story is arithmetically certain even where the latency story is flat:
narrowing the FFN removes its weight bytes from every resident copy, and the
freed capacity buys batch, context or a second model. `analytic - measured` is
the model-versus-reality check; a large value would invalidate the cost model.
KV per token is measured off the live cache, not assumed.

| preset | weights GiB | analytic GiB | analytic - measured | FFN GiB | embeddings GiB | KV KiB/token | max batch ctx 1 | max batch ctx long | peak VRAM GiB |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small | 11.86 | 11.85 | -0.03% | 4.69 | 1.00 | 40.0 | 64 | 64 | 20.67 |
| medium | 12.80 | 12.79 | -0.03% | 5.62 | 1.00 | 40.0 | 64 | 64 | 21.60 |
| large | 13.73 | 13.73 | -0.03% | 6.56 | 1.00 | 40.0 | 64 | 64 | 22.54 |

Roofline utilization at the measured point (`results/s7_memory.csv` carries the
full row set, including every weight bucket):

| preset | prefill GB/s | prefill % peak BW | prefill MFU % | prefill FFN FLOP % | decode GB/s | decode % peak BW | decode MFU % | decode FFN FLOP % |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| small | 103.7 | 12.0 | 26.81 | 86.5 | 225.7 | 26.1 | 0.06 | 85.6 |
| medium | 99.3 | 11.5 | 27.92 | 88.5 | 241.6 | 28.0 | 0.07 | 87.7 |
| large | 98.2 | 11.4 | 29.53 | 89.9 | 258.3 | 29.9 | 0.08 | 89.3 |

_source: `s7_memory_roofline__large__session.json`, `s7_memory_roofline__medium__session.json`, `s7_memory_roofline__small__session.json`_

## Fitted cost model

| group | fitted | rows | intercept ms | ms/token | ms per GB weights | R2 | note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| decode_step | True | 13 | 52.820 | - | 0.2100 | 0.0448 |  |
| prefill | True | 18 | -176.984 | 0.0903 | 12.9470 | 0.9789 |  |

`ms per GB weights` is the fitted marginal cost of one GiB of resident FFN
width in that regime; multiplying it by the Large-minus-Small weight
difference gives the predicted width effect, which the measured ratio is
then compared against. Across the three presets, FFN weight bytes and FFN
FLOPs scale identically with the summed layer width, so a single coefficient
cannot separate the two. The mechanism is pinned down separately: the
per-token saving divided into the removed FLOPs implies ~161 TFLOPS, i.e.
44% of bf16 dense peak, which is a compute-bound rate and not a
bandwidth-bound one.

*decode_step: R2=0.045. This fit is **not identified** -- its
weight coefficient is estimated from only a few distinct weight values
under a dominant nuisance trend -- so the width effect below is reported
for completeness and is not evidence of a mechanism. Use the paired
Large-vs-Small table for that regime.*

**decode_step** predicted width effect: 1.88 GiB less -> 0.423 ms less per step (speedup 1.0080 at batch 1).

*decode_step: dropped collinear regressors: ms_per_token (constant 1.0), ms_per_kv_byte (constant 0.0).*

**prefill** predicted width effect: 1.88 GiB less -> 26.066 ms less per step.

*prefill: dropped collinear regressors: ms_per_kv_byte (constant 0.0).*

## Dynamic switching (s8-s11)

Rendered from the `switching` block each dynamic scenario emits. `tax` is
dynamic-at-W minus static-at-W as a percentage of static: positive means the
switchable path is slower than a physically static model at the same width.

### S8 equivalence gate

| width | max dlogit | argmax agrees | passed | reference |
| --- | --- | --- | --- | --- |
| large | 0.0000 | True | True | dynamic_stock_full_width |
| medium | 0.0000 | True | True | static_medium |
| small | 0.0000 | True | True | static_small |

### S8 decode-path equivalence (KV cache present)

| width | max dlogit | argmax agrees | passed | reference |
| --- | --- | --- | --- | --- |
| large | 0.0000 | True | True | dynamic_stock_full_width_decode |
| medium | 0.0000 | True | True | static_medium_decode |
| small | 0.0000 | True | True | static_small_decode |

### S8 switch-operation cost (host)

| plan | median us | p90 us |
| --- | --- | --- |
| large | 86.23 | 88.50 |
| medium | 86.39 | 89.29 |
| small | 86.78 | 88.88 |

### S8 mechanism tax

| workload | slice_mode | comparison | tax | verdict |
| --- | --- | --- | --- | --- |
| decode | materialize | dyn_large_vs_stock_large | -1.24% | within_noise |
| decode | materialize | dyn_medium_vs_static_medium | -1.45% | within_noise |
| decode | materialize | dyn_small_vs_static_small | -1.08% | within_noise |
| decode | view | dyn_large_vs_stock_large | -1.08% | within_noise |
| decode | view | dyn_medium_vs_static_medium | -1.12% | within_noise |
| decode | view | dyn_small_vs_static_small | -0.58% | within_noise |
| prefill | materialize | dyn_large_vs_stock_large | -0.24% | within_noise |
| prefill | materialize | dyn_medium_vs_static_medium | -0.31% | within_noise |
| prefill | materialize | dyn_small_vs_static_small | -0.58% | within_noise |
| prefill | view | dyn_large_vs_stock_large | -0.21% | within_noise |
| prefill | view | dyn_medium_vs_static_medium | -0.35% | within_noise |
| prefill | view | dyn_small_vs_static_small | -0.58% | within_noise |

### S8 cold-switch penalty (prefill)

| width | cold - warm | verdict |
| --- | --- | --- |
| large | -0.28% | within_noise |
| medium | -0.10% | within_noise |
| small | 0.29% | within_noise |

### S8 null control

| workload | ratio | verdict | passed |
| --- | --- | --- | --- |
| decode | 0.9988 | within_noise | True |
| prefill | 1.0007 | within_noise | True |

### S9 prefill/decode boundary

The capture fraction divides the phase schedule's prefill saving by the
static large-minus-small prefill difference. Where that difference is not
resolvable (low arithmetic intensity) the ratio is noise and is shown as
`n/a` with its raw value.

| grid | prefill delta ms | delta % | prefill capture | resolvable | boundary s->l ms | boundary l->s ms |
| --- | --- | --- | --- | --- | --- | --- |
| L2048_B1 | 26.98 | 20.9% | 0.991 | yes | -0.03 | 0.65 |
| L2048_B4 | 100.23 | 14.2% | 0.994 | yes | 0.64 | 1.27 |
| L512_B1 | 0.39 | 0.7% | n/a (raw 2.45) | no | -0.18 | -0.10 |
| L512_B4 | 25.87 | 21.7% | 1.008 | yes | 0.49 | 0.77 |

### S10 iteration-level switching

`width delta` is the static large-minus-small step difference. Where it
is not resolvable the alternation overhead is within noise by
construction and must not be read as "switching is free".

| grid | width delta ms | width resolvable | alternation overhead | const large ms | const small ms |
| --- | --- | --- | --- | --- | --- |
| L2048_B1 | -0.109 | no | -0.02% | 55.143 | 55.253 |
| L2048_B8 | 0.010 | no | 0.06% | 56.966 | 56.956 |
| L512_B1 | -0.339 | no | -0.00% | 55.284 | 55.623 |
| L512_B8 | -0.060 | no | 0.03% | 56.791 | 56.851 |

Every switching schedule in the record (the table above shows only
`alternate`); the worst row bounds the per-schedule switching cost:

| grid | schedule | alternation overhead | switches |
| --- | --- | --- | --- |
| L2048_B1 | alt_large_small | -0.02% | 96 |
| L2048_B1 | block16_large_small | 0.23% | 96 |
| L2048_B1 | block1_large_small | 0.06% | 96 |
| L2048_B1 | block4_large_small | 0.25% | 96 |
| L2048_B1 | rand_large_small | 0.22% | 96 |
| L2048_B8 | alt_large_small | 0.06% | 96 |
| L2048_B8 | block16_large_small | -0.00% | 96 |
| L2048_B8 | block1_large_small | 0.02% | 96 |
| L2048_B8 | block4_large_small | 0.43% | 96 |
| L2048_B8 | rand_large_small | 0.11% | 96 |
| L512_B1 | alt_large_small | -0.00% | 96 |
| L512_B1 | block16_large_small | -0.14% | 96 |
| L512_B1 | block1_large_small | 0.07% | 96 |
| L512_B1 | block4_large_small | 0.23% | 96 |
| L512_B1 | rand_large_small | 0.10% | 96 |
| L512_B8 | alt_large_small | 0.03% | 96 |
| L512_B8 | block16_large_small | 0.31% | 96 |
| L512_B8 | block1_large_small | 0.33% | 96 |
| L512_B8 | block4_large_small | 0.14% | 96 |
| L512_B8 | rand_large_small | 0.06% | 96 |

### S11 weights per option (GiB)

| option | GiB |
| --- | --- |
| dynamic_full | 13.73 |
| static_medium | 12.80 |
| static_small | 11.86 |
| static_small_plus_large_full | 25.59 |

### S11 max batch before OOM

| model/context | max batch |
| --- | --- |
| dynamic_L1 | 128 |
| dynamic_L2048 | 32 |
| static_medium_L1 | 128 |
| static_medium_L2048 | 32 |
| static_small_L1 | 128 |
| static_small_L2048 | 32 |

_Every option reached the same max batch per context (ctx 1: 128, ctx 2048: 32).
The probe runs with one model resident at a time, so this is not a
co-residency artefact: in these regimes the ~1.9 GiB FFN-width
difference does not move the batch cap (the short-context row is
`--capacity-cap`-limited (128); at long context activations and
KV dominate the weight delta)._

Retarget cost (host apply): median 86.95 us vs a reload of 6.0 s.

_A dynamic scenario missing here did not run or did not complete; that is not
evidence of absence._

## Provenance

Every table above is derived from these scenario records. The raw records live
in the git-ignored `run-output/`; the extracted, reviewable copies are the
tracked `results/*.json` and `results/*.csv` files written by
`analyze_latency.py`.

| scenario | records | files |
| --- | --- | --- |
| s0_harness_validation | 1 | `s0_harness_validation__all__local.json` |
| s10_switch_iteration | 1 | `s10_switch_iteration__all__session.json` |
| s11_switch_flexibility | 1 | `s11_switch_flexibility__all__session.json` |
| s1_decode_step | 2 | `s1_decode_step__all__session.json`<br>`s1_decode_step__all__smoke.json` |
| s2_prefill | 1 | `s2_prefill__all__session.json` |
| s3_batch_decode | 2 | `s3_batch_decode__all__s3b.json`<br>`s3_batch_decode__all__session.json` |
| s4_end_to_end | 3 | `s4_end_to_end__large__session.json`<br>`s4_end_to_end__medium__session.json`<br>`s4_end_to_end__small__session.json` |
| s5_backends | 1 | `s5_backends__all__session.json` |
| s6_layer_profile | 3 | `s6_layer_profile__large__session.json`<br>`s6_layer_profile__medium__session.json`<br>`s6_layer_profile__small__session.json` |
| s7_memory_roofline | 3 | `s7_memory_roofline__large__session.json`<br>`s7_memory_roofline__medium__session.json`<br>`s7_memory_roofline__small__session.json` |
| s8_switch_mechanism | 1 | `s8_switch_mechanism__all__session.json` |
| s9_switch_phase | 1 | `s9_switch_phase__all__session.json` |

