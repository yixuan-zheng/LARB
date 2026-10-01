# FFN width latency profile

Generated from `results/latency_profile.json`. Every ratio is a *paired* mean
ratio over shuffled, interleaved samples; `verdict` follows the pre-registered
rule (bootstrap CI excludes 1.0 **and** |median delta| > 2%).

## Coverage

| field | value |
| --- | --- |
| records | 16 |
| completed records | 16 |
| scenarios | s0_harness_validation, s1_decode_step, s2_prefill, s3_batch_decode, s4_end_to_end, s5_backends, s6_layer_profile, s7_memory_roofline |
| utilization rows | 84 |
| comparison rows | 87 |
| appreciable effects | 21 |
| MDD floor | 0.10% |
| residual harness bias | 0.90% |

## Utilization per configuration

| scenario | config | preset | gpu ms | alpha ms | BW GB/s | BW % peak | MFU % | tok/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| s0_harness_validation | a | unknown | 0.110 | 0.023 | - | - | - | - |
| s0_harness_validation | b | unknown | 0.109 | 0.023 | - | - | - | - |
| s0_harness_validation | big | unknown | 2.603 | 0.025 | - | - | - | - |
| s0_harness_validation | flush_off | unknown | 0.186 | 0.025 | - | - | - | - |
| s0_harness_validation | flush_on | unknown | 0.186 | 0.026 | - | - | - | - |
| s0_harness_validation | n16384 | unknown | 0.185 | 0.025 | - | - | - | - |
| s0_harness_validation | n32768 | unknown | 0.287 | 0.026 | - | - | - | - |
| s0_harness_validation | n4096 | unknown | 0.075 | 0.025 | - | - | - | - |
| s0_harness_validation | n65536 | unknown | 0.490 | 0.026 | - | - | - | - |
| s0_harness_validation | n8192 | unknown | 0.114 | 0.025 | - | - | - | - |
| s0_harness_validation | small | small | 1.169 | 0.025 | - | - | - | - |
| s1_decode_step | large_L128 | large | 55.051 | 0.033 | 267.8 | 31.0 | 0.039 | 18.2 |
| s1_decode_step | large_L128 | large | 54.597 | 0.034 | 270.1 | 31.3 | 0.039 | 18.3 |
| s1_decode_step | large_L2048 | large | 56.628 | 0.031 | 260.4 | 30.1 | 0.039 | 17.7 |
| s1_decode_step | large_L512 | large | 56.543 | 0.031 | 260.8 | 30.2 | 0.038 | 17.7 |
| s1_decode_step | large_L512 | large | 56.500 | 0.032 | 261.0 | 30.2 | 0.038 | 17.7 |
| s1_decode_step | medium_L128 | medium | 54.751 | 0.034 | 250.9 | 29.0 | 0.034 | 18.3 |
| s1_decode_step | medium_L2048 | medium | 56.562 | 0.031 | 242.9 | 28.1 | 0.034 | 17.7 |
| s1_decode_step | medium_L512 | medium | 56.332 | 0.033 | 243.9 | 28.2 | 0.034 | 17.8 |
| s1_decode_step | small_L128 | small | 54.675 | 0.035 | 232.9 | 27.0 | 0.029 | 18.3 |
| s1_decode_step | small_L128 | small | 54.136 | 0.034 | 235.2 | 27.2 | 0.029 | 18.5 |
| s1_decode_step | small_L2048 | small | 56.230 | 0.031 | 226.4 | 26.2 | 0.029 | 17.8 |
| s1_decode_step | small_L512 | small | 56.196 | 0.032 | 226.6 | 26.2 | 0.029 | 17.8 |
| s1_decode_step | small_L512 | small | 55.967 | 0.033 | 227.5 | 26.3 | 0.029 | 17.9 |
| s2_prefill | large_L128_B1 | large | 57.931 | 0.030 | 254.5 | 29.5 | 4.721 | 2209.5 |
| s2_prefill | large_L128_B4 | large | 58.646 | 0.031 | 251.4 | 29.1 | 18.654 | 8730.3 |
| s2_prefill | large_L2048_B1 | large | 160.077 | 0.032 | 92.1 | 10.7 | 27.842 | 12793.8 |
| s2_prefill | large_L2048_B4 | large | 810.975 | 0.042 | 18.2 | 2.1 | 21.983 | 10101.4 |
| s2_prefill | large_L512_B1 | large | 61.530 | 0.031 | 239.6 | 27.7 | 17.907 | 8321.2 |
| s2_prefill | large_L512_B4 | large | 148.381 | 0.032 | 99.4 | 11.5 | 29.702 | 13802.3 |
| s2_prefill | medium_L128_B1 | medium | 57.543 | 0.030 | 238.8 | 27.6 | 4.135 | 2224.4 |
| s2_prefill | medium_L128_B4 | medium | 57.960 | 0.031 | 237.0 | 27.4 | 16.419 | 8833.6 |
| s2_prefill | medium_L2048_B1 | medium | 146.519 | 0.032 | 93.8 | 10.9 | 26.533 | 13977.8 |
| s2_prefill | medium_L2048_B4 | medium | 761.467 | 0.042 | 18.0 | 2.1 | 20.421 | 10758.2 |
| s2_prefill | medium_L512_B1 | medium | 60.929 | 0.032 | 225.5 | 26.1 | 15.747 | 8403.2 |
| s2_prefill | medium_L512_B4 | medium | 135.184 | 0.033 | 101.6 | 11.8 | 28.389 | 15149.7 |
| s2_prefill | small_L128_B1 | small | 57.202 | 0.031 | 222.6 | 25.8 | 3.537 | 2237.7 |
| s2_prefill | small_L128_B4 | small | 57.271 | 0.031 | 222.3 | 25.7 | 14.131 | 8939.9 |
| s2_prefill | small_L2048_B1 | small | 133.305 | 0.032 | 95.5 | 11.1 | 24.891 | 15363.2 |
| s2_prefill | small_L2048_B4 | small | 710.980 | 0.041 | 17.9 | 2.1 | 18.668 | 11522.1 |
| s2_prefill | small_L512_B1 | small | 60.185 | 0.031 | 211.5 | 24.5 | 13.576 | 8507.1 |
| s2_prefill | small_L512_B4 | small | 122.202 | 0.032 | 104.2 | 12.1 | 26.745 | 16759.1 |
| s3_batch_decode | large_L128_B1 | large | 54.260 | 0.033 | 271.8 | 31.5 | 0.039 | 18.4 |
| s3_batch_decode | large_L128_B16 | large | 56.676 | 0.036 | 261.6 | 30.3 | 0.605 | 282.3 |
| s3_batch_decode | large_L128_B4 | large | 55.193 | 0.032 | 267.5 | 31.0 | 0.155 | 72.5 |
| s3_batch_decode | large_L128_B8 | large | 55.693 | 0.031 | 265.5 | 30.7 | 0.308 | 143.6 |
| s3_batch_decode | large_L1_B1 | large | 54.411 | 0.038 | 271.0 | 31.4 | 0.039 | 18.4 |
| s3_batch_decode | large_L1_B16 | large | 55.556 | 0.035 | 265.4 | 30.7 | 0.614 | 288.0 |
| s3_batch_decode | large_L1_B4 | large | 55.636 | 0.038 | 265.0 | 30.7 | 0.153 | 71.9 |
| s3_batch_decode | large_L1_B8 | large | 55.376 | 0.033 | 266.3 | 30.8 | 0.308 | 144.5 |
| s3_batch_decode | large_L2048_B1 | large | 56.132 | 0.032 | 263.2 | 30.5 | 0.039 | 17.8 |
| s3_batch_decode | large_L2048_B4 | large | 58.285 | 0.038 | 254.9 | 29.5 | 0.151 | 68.6 |
| s3_batch_decode | medium_L128_B1 | medium | 53.823 | 0.033 | 255.4 | 29.6 | 0.035 | 18.6 |
| s3_batch_decode | medium_L128_B16 | medium | 56.525 | 0.033 | 244.5 | 28.3 | 0.528 | 283.1 |
| s3_batch_decode | medium_L128_B4 | medium | 55.158 | 0.034 | 249.5 | 28.9 | 0.135 | 72.5 |
| s3_batch_decode | medium_L128_B8 | medium | 55.344 | 0.031 | 249.0 | 28.8 | 0.269 | 144.6 |
| s3_batch_decode | medium_L1_B1 | medium | 54.263 | 0.039 | 253.2 | 29.3 | 0.034 | 18.4 |
| s3_batch_decode | medium_L1_B16 | medium | 55.124 | 0.033 | 249.2 | 28.8 | 0.538 | 290.3 |
| s3_batch_decode | medium_L1_B4 | medium | 55.396 | 0.039 | 248.0 | 28.7 | 0.134 | 72.2 |
| s3_batch_decode | medium_L1_B8 | medium | 55.121 | 0.034 | 249.2 | 28.8 | 0.269 | 145.1 |
| s3_batch_decode | medium_L2048_B1 | medium | 56.006 | 0.032 | 245.8 | 28.4 | 0.034 | 17.9 |
| s3_batch_decode | medium_L2048_B4 | medium | 57.866 | 0.037 | 239.3 | 27.7 | 0.133 | 69.1 |
| s3_batch_decode | small_L128_B1 | small | 53.733 | 0.034 | 237.0 | 27.4 | 0.030 | 18.6 |
| s3_batch_decode | small_L128_B16 | small | 55.965 | 0.034 | 229.0 | 26.5 | 0.453 | 285.9 |
| s3_batch_decode | small_L128_B4 | small | 54.709 | 0.034 | 233.1 | 27.0 | 0.116 | 73.1 |
| s3_batch_decode | small_L128_B8 | small | 55.139 | 0.032 | 231.7 | 26.8 | 0.230 | 145.1 |
| s3_batch_decode | small_L1_B1 | small | 54.138 | 0.037 | 235.2 | 27.2 | 0.029 | 18.5 |
| s3_batch_decode | small_L1_B16 | small | 54.934 | 0.032 | 231.8 | 26.8 | 0.459 | 291.3 |
| s3_batch_decode | small_L1_B4 | small | 55.176 | 0.040 | 230.8 | 26.7 | 0.114 | 72.5 |
| s3_batch_decode | small_L1_B8 | small | 54.840 | 0.032 | 232.2 | 26.9 | 0.230 | 145.9 |
| s3_batch_decode | small_L2048_B1 | small | 55.712 | 0.031 | 229.0 | 26.5 | 0.029 | 17.9 |
| s3_batch_decode | small_L2048_B4 | small | 57.717 | 0.035 | 222.5 | 25.8 | 0.114 | 69.3 |
| s5_backends | large_compile | large | 114.799 | 0.034 | 128.4 | 14.9 | 38.390 | 17839.9 |
| s5_backends | large_eager | large | 150.521 | 0.034 | 98.0 | 11.3 | 29.279 | 13606.1 |
| s5_backends | medium_compile | medium | 103.306 | 0.034 | 133.0 | 15.4 | 37.149 | 19824.6 |
| s5_backends | medium_eager | medium | 137.666 | 0.032 | 99.8 | 11.6 | 27.877 | 14876.6 |
| s5_backends | small_compile | small | 92.347 | 0.034 | 137.9 | 16.0 | 35.392 | 22177.1 |
| s5_backends | small_eager | small | 124.059 | 0.033 | 102.6 | 11.9 | 26.345 | 16508.3 |
| s7_memory_roofline | decode | unknown | 57.272 | 0.031 | - | - | - | - |
| s7_memory_roofline | decode | unknown | 57.062 | 0.032 | - | - | - | - |
| s7_memory_roofline | decode | unknown | 56.613 | 0.031 | - | - | - | - |
| s7_memory_roofline | prefill | unknown | 150.098 | 0.032 | - | - | - | - |
| s7_memory_roofline | prefill | unknown | 138.363 | 0.032 | - | - | - | - |
| s7_memory_roofline | prefill | unknown | 122.835 | 0.032 | - | - | - | - |

## Large vs Small (paired)

| scenario | grid | metric | speedup | ratio 95% CI | MDD | median delta | verdict |
| --- | --- | --- | --- | --- | --- | --- | --- |
| s0_harness_validation | known_2x_compute | wall_ms | 2.1716 | [0.4558, 0.4663] | 0.31% | -54.51% | appreciable |
| s0_harness_validation | l2_flush_probe | wall_ms | 0.9969 | [0.9983, 1.0091] | 0.54% | -0.08% | within_noise |
| s0_harness_validation | null_diff | wall_ms | 1.0091 | [0.9760, 1.0028] | 1.40% | -0.54% | within_noise |
| s1_decode_step | L128 | gpu_ms | 1.0079 | [0.9892, 0.9955] | 0.32% | -0.68% | within_noise |
| s1_decode_step | L128 | gpu_ms | 1.0050 | [0.9914, 0.9988] | 0.38% | -0.54% | within_noise |
| s1_decode_step | L128 | gpu_ms | 1.0057 | [0.9898, 0.9994] | 0.51% | -0.84% | within_noise |
| s1_decode_step | L128 | wall_ms | 1.0078 | [0.9893, 0.9956] | 0.32% | -0.68% | within_noise |
| s1_decode_step | L128 | wall_ms | 1.0050 | [0.9914, 0.9989] | 0.38% | -0.54% | within_noise |
| s1_decode_step | L128 | wall_ms | 1.0057 | [0.9898, 0.9995] | 0.51% | -0.84% | within_noise |
| s1_decode_step | L2048 | gpu_ms | 1.0084 | [0.9886, 0.9945] | 0.31% | -0.70% | within_noise |
| s1_decode_step | L2048 | gpu_ms | 1.0024 | [0.9955, 0.9999] | 0.23% | -0.12% | within_noise |
| s1_decode_step | L2048 | wall_ms | 1.0084 | [0.9886, 0.9945] | 0.31% | -0.70% | within_noise |
| s1_decode_step | L2048 | wall_ms | 1.0024 | [0.9955, 0.9999] | 0.23% | -0.12% | within_noise |
| s1_decode_step | L512 | gpu_ms | 1.0066 | [0.9912, 0.9954] | 0.22% | -0.61% | within_noise |
| s1_decode_step | L512 | gpu_ms | 1.0031 | [0.9942, 0.9997] | 0.29% | -0.37% | within_noise |
| s1_decode_step | L512 | gpu_ms | 1.0088 | [0.9868, 0.9951] | 0.44% | -0.94% | within_noise |
| s1_decode_step | L512 | wall_ms | 1.0066 | [0.9913, 0.9955] | 0.22% | -0.61% | within_noise |
| s1_decode_step | L512 | wall_ms | 1.0030 | [0.9942, 0.9997] | 0.29% | -0.37% | within_noise |
| s1_decode_step | L512 | wall_ms | 1.0088 | [0.9868, 0.9951] | 0.44% | -0.94% | within_noise |
| s2_prefill | L128_B1 | gpu_ms | 1.0131 | [0.9830, 0.9909] | 0.43% | -1.26% | within_noise |
| s2_prefill | L128_B1 | gpu_ms | 1.0053 | [0.9899, 0.9994] | 0.50% | -0.67% | within_noise |
| s2_prefill | L128_B1 | wall_ms | 1.0130 | [0.9831, 0.9910] | 0.42% | -1.26% | within_noise |
| s2_prefill | L128_B1 | wall_ms | 1.0053 | [0.9898, 0.9994] | 0.50% | -0.67% | within_noise |
| s2_prefill | L128_B4 | gpu_ms | 1.0275 | [0.9629, 0.9796] | 1.00% | -2.34% | appreciable |
| s2_prefill | L128_B4 | gpu_ms | 1.0161 | [0.9759, 0.9892] | 0.80% | -1.17% | within_noise |
| s2_prefill | L128_B4 | wall_ms | 1.0275 | [0.9629, 0.9797] | 1.00% | -2.34% | appreciable |
| s2_prefill | L128_B4 | wall_ms | 1.0161 | [0.9759, 0.9892] | 0.80% | -1.17% | within_noise |
| s2_prefill | L2048_B1 | gpu_ms | 1.2017 | [0.8305, 0.8340] | 0.19% | -16.72% | appreciable |
| s2_prefill | L2048_B1 | gpu_ms | 1.0916 | [0.9140, 0.9187] | 0.26% | -8.47% | appreciable |
| s2_prefill | L2048_B1 | wall_ms | 1.2016 | [0.8305, 0.8340] | 0.19% | -16.72% | appreciable |
| s2_prefill | L2048_B1 | wall_ms | 1.0916 | [0.9140, 0.9187] | 0.26% | -8.47% | appreciable |
| s2_prefill | L2048_B4 | gpu_ms | 1.1414 | [0.8753, 0.8769] | 0.10% | -12.33% | appreciable |
| s2_prefill | L2048_B4 | gpu_ms | 1.0660 | [0.9370, 0.9392] | 0.12% | -6.10% | appreciable |
| s2_prefill | L2048_B4 | wall_ms | 1.1414 | [0.8753, 0.8769] | 0.10% | -12.33% | appreciable |
| s2_prefill | L2048_B4 | wall_ms | 1.0660 | [0.9370, 0.9392] | 0.12% | -6.10% | appreciable |
| s2_prefill | L512_B1 | gpu_ms | 1.0209 | [0.9756, 0.9835] | 0.41% | -2.19% | appreciable |
| s2_prefill | L512_B1 | gpu_ms | 1.0098 | [0.9879, 0.9933] | 0.29% | -0.98% | within_noise |
| s2_prefill | L512_B1 | wall_ms | 1.0209 | [0.9756, 0.9835] | 0.41% | -2.18% | appreciable |
| s2_prefill | L512_B1 | wall_ms | 1.0098 | [0.9879, 0.9933] | 0.29% | -0.97% | within_noise |
| s2_prefill | L512_B4 | gpu_ms | 1.2144 | [0.8209, 0.8259] | 0.29% | -17.64% | appreciable |
| s2_prefill | L512_B4 | gpu_ms | 1.0980 | [0.9085, 0.9131] | 0.25% | -8.89% | appreciable |
| s2_prefill | L512_B4 | wall_ms | 1.2143 | [0.8209, 0.8259] | 0.30% | -17.64% | appreciable |
| s2_prefill | L512_B4 | wall_ms | 1.0979 | [0.9085, 0.9131] | 0.25% | -8.89% | appreciable |
| s3_batch_decode | L128_B1 | gpu_ms | 1.0095 | [0.9870, 0.9944] | 0.39% | -0.97% | within_noise |
| s3_batch_decode | L128_B1 | gpu_ms | 1.0063 | [0.9891, 0.9983] | 0.49% | -0.81% | within_noise |
| s3_batch_decode | L128_B1 | wall_ms | 1.0095 | [0.9870, 0.9944] | 0.40% | -0.98% | within_noise |
| s3_batch_decode | L128_B1 | wall_ms | 1.0063 | [0.9891, 0.9983] | 0.49% | -0.81% | within_noise |
| s3_batch_decode | L128_B16 | gpu_ms | 1.0096 | [0.9826, 0.9974] | 0.80% | -1.26% | within_noise |
| s3_batch_decode | L128_B16 | gpu_ms | 1.0039 | [0.9920, 1.0002] | 0.44% | -0.27% | within_noise |
| s3_batch_decode | L128_B16 | wall_ms | 1.0096 | [0.9825, 0.9974] | 0.80% | -1.26% | within_noise |
| s3_batch_decode | L128_B16 | wall_ms | 1.0039 | [0.9919, 1.0001] | 0.44% | -0.27% | within_noise |
| s3_batch_decode | L128_B4 | gpu_ms | 1.0078 | [0.9874, 0.9977] | 0.56% | -0.88% | within_noise |
| s3_batch_decode | L128_B4 | gpu_ms | 1.0009 | [0.9944, 1.0039] | 0.50% | -0.06% | within_noise |
| s3_batch_decode | L128_B4 | wall_ms | 1.0078 | [0.9874, 0.9978] | 0.56% | -0.87% | within_noise |
| s3_batch_decode | L128_B4 | wall_ms | 1.0008 | [0.9945, 1.0039] | 0.50% | -0.06% | within_noise |
| s3_batch_decode | L128_B8 | gpu_ms | 1.0089 | [0.9883, 0.9938] | 0.29% | -0.99% | within_noise |
| s3_batch_decode | L128_B8 | gpu_ms | 1.0067 | [0.9919, 0.9949] | 0.16% | -0.63% | within_noise |
| s3_batch_decode | L128_B8 | wall_ms | 1.0088 | [0.9883, 0.9938] | 0.29% | -0.99% | within_noise |
| s3_batch_decode | L128_B8 | wall_ms | 1.0067 | [0.9920, 0.9949] | 0.16% | -0.62% | within_noise |
| s3_batch_decode | L1_B1 | gpu_ms | 1.0058 | [0.9924, 0.9964] | 0.21% | -0.50% | within_noise |
| s3_batch_decode | L1_B1 | gpu_ms | 1.0036 | [0.9949, 0.9980] | 0.17% | -0.27% | within_noise |
| s3_batch_decode | L1_B1 | wall_ms | 1.0057 | [0.9924, 0.9964] | 0.21% | -0.50% | within_noise |
| s3_batch_decode | L1_B1 | wall_ms | 1.0036 | [0.9949, 0.9980] | 0.17% | -0.27% | within_noise |
| s3_batch_decode | L1_B16 | gpu_ms | 1.0109 | [0.9860, 0.9926] | 0.35% | -1.12% | within_noise |
| s3_batch_decode | L1_B16 | gpu_ms | 1.0059 | [0.9914, 0.9971] | 0.31% | -0.78% | within_noise |
| s3_batch_decode | L1_B16 | wall_ms | 1.0109 | [0.9860, 0.9926] | 0.35% | -1.12% | within_noise |
| s3_batch_decode | L1_B16 | wall_ms | 1.0059 | [0.9913, 0.9971] | 0.31% | -0.78% | within_noise |
| s3_batch_decode | L1_B4 | gpu_ms | 1.0073 | [0.9903, 0.9958] | 0.29% | -0.83% | within_noise |
| s3_batch_decode | L1_B4 | gpu_ms | 1.0037 | [0.9950, 0.9976] | 0.13% | -0.43% | within_noise |
| s3_batch_decode | L1_B4 | wall_ms | 1.0072 | [0.9903, 0.9958] | 0.29% | -0.83% | within_noise |
| s3_batch_decode | L1_B4 | wall_ms | 1.0037 | [0.9950, 0.9976] | 0.13% | -0.43% | within_noise |
| s3_batch_decode | L1_B8 | gpu_ms | 1.0106 | [0.9867, 0.9927] | 0.32% | -0.97% | within_noise |
| s3_batch_decode | L1_B8 | gpu_ms | 1.0049 | [0.9932, 0.9970] | 0.21% | -0.46% | within_noise |
| s3_batch_decode | L1_B8 | wall_ms | 1.0105 | [0.9867, 0.9928] | 0.32% | -0.97% | within_noise |
| s3_batch_decode | L1_B8 | wall_ms | 1.0049 | [0.9932, 0.9970] | 0.21% | -0.46% | within_noise |
| s3_batch_decode | L2048_B1 | gpu_ms | 1.0075 | [0.9892, 0.9967] | 0.41% | -0.75% | within_noise |
| s3_batch_decode | L2048_B1 | gpu_ms | 1.0015 | [0.9940, 1.0030] | 0.48% | -0.23% | within_noise |
| s3_batch_decode | L2048_B1 | wall_ms | 1.0075 | [0.9892, 0.9967] | 0.41% | -0.75% | within_noise |
| s3_batch_decode | L2048_B1 | wall_ms | 1.0015 | [0.9940, 1.0030] | 0.48% | -0.22% | within_noise |
| s3_batch_decode | L2048_B4 | gpu_ms | 1.0100 | [0.9850, 0.9950] | 0.54% | -0.98% | within_noise |
| s3_batch_decode | L2048_B4 | gpu_ms | 1.0055 | [0.9893, 1.0009] | 0.62% | -0.72% | within_noise |
| s3_batch_decode | L2048_B4 | wall_ms | 1.0100 | [0.9850, 0.9950] | 0.54% | -0.97% | within_noise |
| s3_batch_decode | L2048_B4 | wall_ms | 1.0054 | [0.9893, 1.0009] | 0.62% | -0.72% | within_noise |
| s5_backends | compile | gpu_ms | 1.2419 | [0.7993, 0.8112] | 0.69% | -19.56% | appreciable |
| s5_backends | compile | gpu_ms | 1.1088 | [0.8956, 0.9081] | 0.68% | -10.01% | appreciable |
| s5_backends | eager | gpu_ms | 1.2160 | [0.8193, 0.8254] | 0.36% | -17.58% | appreciable |
| s5_backends | eager | gpu_ms | 1.0951 | [0.9094, 0.9168] | 0.41% | -8.54% | appreciable |

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

**decode_step** predicted width effect: 1.88 GiB less -> 0.423 ms less per step (speedup 1.0080 at batch 1).

*decode_step: dropped collinear regressors: ms_per_token (constant 1.0), ms_per_kv_byte (constant 0.0).*

**prefill** predicted width effect: 1.88 GiB less -> 26.066 ms less per step.

*prefill: dropped collinear regressors: ms_per_kv_byte (constant 0.0).*

