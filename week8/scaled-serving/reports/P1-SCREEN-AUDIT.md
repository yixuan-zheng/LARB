# P1 slope-record audit (CPU-only)

Generated: 2026-11-17T01:31:33.342639+00:00

Source: `week7/scaled-serving/results/p1/runs/slope/requests`

## Summary

### gate-preview:preview_all

| metric | value |
|---|---:|
| gain_4k_to_8k | -0.083 |
| answer_change_fraction | 0.500 |
| accuracy_8k | 0.167 |
| cap_rate_8k | 0.208 |
| thinking_median_8k | 8192.000 |
| pre_registered_and | False |
| p1_summariser_or | False |

### gate-screen:screen_aime2023

| metric | value |
|---|---:|
| gain_4k_to_8k | 0.292 |
| answer_change_fraction | 0.708 |
| accuracy_8k | 0.542 |
| cap_rate_8k | 0.083 |
| thinking_median_8k | 8192.000 |
| pre_registered_and | True |
| p1_summariser_or | True |

### gate-screen:screen_all

| metric | value |
|---|---:|
| gain_4k_to_8k | 0.167 |
| answer_change_fraction | 0.688 |
| accuracy_8k | 0.438 |
| cap_rate_8k | 0.104 |
| thinking_median_8k | 8192.000 |
| pre_registered_and | True |
| p1_summariser_or | True |

### gate-screen:screen_hmmt2024

| metric | value |
|---|---:|
| gain_4k_to_8k | 0.042 |
| answer_change_fraction | 0.667 |
| accuracy_8k | 0.333 |
| cap_rate_8k | 0.125 |
| thinking_median_8k | 8192.000 |
| pre_registered_and | False |
| p1_summariser_or | False |

## Per-pool accuracy (safe normalised grader)

| condition | pool | arm | n | correct | accuracy | 95% CI | cap rate | missing box |
|---|---|---|---:|---:|---:|---|---:|---:|
| gate-screen | screen_all | fixed4k | 48 | 13 | 0.271 | [0.166, 0.410] | 0.250 | 0.229 |
| gate-screen | screen_all | fixed6k | 48 | 15 | 0.312 | [0.199, 0.453] | 0.208 | 0.188 |
| gate-screen | screen_all | fixed8k | 48 | 21 | 0.438 | [0.307, 0.577] | 0.104 | 0.083 |
| gate-screen | screen_aime2023 | fixed4k | 24 | 6 | 0.250 | [0.120, 0.449] | 0.292 | 0.250 |
| gate-screen | screen_aime2023 | fixed6k | 24 | 9 | 0.375 | [0.212, 0.573] | 0.333 | 0.333 |
| gate-screen | screen_aime2023 | fixed8k | 24 | 13 | 0.542 | [0.351, 0.721] | 0.083 | 0.042 |
| gate-screen | screen_hmmt2024 | fixed4k | 24 | 7 | 0.292 | [0.149, 0.492] | 0.208 | 0.208 |
| gate-screen | screen_hmmt2024 | fixed6k | 24 | 6 | 0.250 | [0.120, 0.449] | 0.083 | 0.042 |
| gate-screen | screen_hmmt2024 | fixed8k | 24 | 8 | 0.333 | [0.180, 0.533] | 0.125 | 0.125 |
| gate-preview | preview_all | fixed4k | 24 | 6 | 0.250 | [0.120, 0.449] | 0.292 | 0.292 |
| gate-preview | preview_all | fixed6k | 24 | 7 | 0.292 | [0.149, 0.492] | 0.167 | 0.125 |
| gate-preview | preview_all | fixed8k | 24 | 4 | 0.167 | [0.067, 0.359] | 0.208 | 0.208 |

## Paired 4k vs 8k (safe normalised grader)

| condition | pool | n pairs | 4k only | 8k only | neither | both | discordance | gain | answer change |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| gate-screen | screen_all | 48 | 1 | 9 | 26 | 12 | 0.208 | +0.167 | 0.688 |
| gate-screen | screen_aime2023 | 24 | 0 | 7 | 11 | 6 | 0.292 | +0.292 | 0.708 |
| gate-screen | screen_hmmt2024 | 24 | 1 | 2 | 15 | 6 | 0.125 | +0.042 | 0.667 |
| gate-preview | preview_all | 24 | 2 | 0 | 18 | 4 | 0.083 | -0.083 | 0.500 |

## Grading-contract findings

Raw-Math-Verify failures fixed by safe normalised grading: **5**

By source: `{'MathArena/hmmt_feb_2024': 5}`

Loose-Math-Verify false positives rejected by safe grading: **1**

By source: `{'MathArena/cmimc_2025': 1}`

## Prompt checks

Checked records: 216; issues: 0

## Power

| questions | seeds | ICC | effective pairs | MDE @20% | MDE @30% |
|---:|---:|---:|---:|---:|---:|
| 24 | 1 | 0.2 | 24 | 25.6 | 31.3 |
| 24 | 1 | 0.4 | 24 | 25.6 | 31.3 |
| 24 | 1 | 0.6 | 24 | 25.6 | 31.3 |
| 24 | 4 | 0.2 | 60 | 16.2 | 19.8 |
| 24 | 4 | 0.4 | 44 | 19.0 | 23.2 |
| 24 | 4 | 0.6 | 34 | 21.4 | 26.2 |
| 25 | 1 | 0.2 | 25 | 25.1 | 30.7 |
| 25 | 1 | 0.4 | 25 | 25.1 | 30.7 |
| 25 | 1 | 0.6 | 25 | 25.1 | 30.7 |
| 25 | 4 | 0.2 | 62 | 15.8 | 19.4 |
| 25 | 4 | 0.4 | 45 | 18.6 | 22.8 |
| 25 | 4 | 0.6 | 36 | 21.0 | 25.7 |
| 48 | 1 | 0.2 | 48 | 18.1 | 22.1 |
| 48 | 1 | 0.4 | 48 | 18.1 | 22.1 |
| 48 | 1 | 0.6 | 48 | 18.1 | 22.1 |
| 48 | 4 | 0.2 | 120 | 11.4 | 14.0 |
| 48 | 4 | 0.4 | 87 | 13.4 | 16.4 |
| 48 | 4 | 0.6 | 69 | 15.1 | 18.5 |
| 192 | 1 | 0.2 | 192 | 9.0 | 11.1 |
| 192 | 1 | 0.4 | 192 | 9.0 | 11.1 |
| 192 | 1 | 0.6 | 192 | 9.0 | 11.1 |
| 192 | 4 | 0.2 | 480 | 5.7 | 7.0 |
| 192 | 4 | 0.4 | 349 | 6.7 | 8.2 |
| 192 | 4 | 0.6 | 274 | 7.6 | 9.3 |
| 216 | 1 | 0.2 | 216 | 8.5 | 10.4 |
| 216 | 1 | 0.4 | 216 | 8.5 | 10.4 |
| 216 | 1 | 0.6 | 216 | 8.5 | 10.4 |
| 216 | 4 | 0.2 | 540 | 5.4 | 6.6 |
| 216 | 4 | 0.4 | 393 | 6.3 | 7.7 |
| 216 | 4 | 0.6 | 309 | 7.1 | 8.7 |

