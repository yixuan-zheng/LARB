# CPU pre-calibration for the 240 s SLO

Generated: 2026-11-17T01:32:13.538220+00:00

## Observed P1 points (180 s)

| rate/h | signal | miss rate | p50 latency | p90 latency |
|---:|---:|---:|---:|---:|
| 500 | 88 | 0.000 | 149 | 164 |
| 650 | 113 | 0.000 | 147 | 160 |
| 800 | 140 | 0.000 | 148 | 164 |
| 931 | 217 | 0.747 | 230 | 287 |
| 1164 | 272 | 0.610 | 218 | 300 |
| 1397 | 326 | 0.883 | 456 | 689 |

## Predicted 240 s curve (load-independent, 5 seeds)

| rate/h | mean miss | min | max |
|---:|---:|---:|---:|
| 500 | 0.000 | 0.000 | 0.000 |
| 550 | 0.000 | 0.000 | 0.000 |
| 600 | 0.000 | 0.000 | 0.000 |
| 650 | 0.000 | 0.000 | 0.000 |
| 700 | 0.000 | 0.000 | 0.000 |
| 750 | 0.000 | 0.000 | 0.000 |
| 800 | 0.000 | 0.000 | 0.000 |
| 850 | 0.000 | 0.000 | 0.000 |
| 900 | 0.001 | 0.000 | 0.007 |
| 950 | 0.010 | 0.000 | 0.046 |
| 1000 | 0.087 | 0.000 | 0.395 |
| 1050 | 0.193 | 0.000 | 0.709 |
| 1100 | 0.449 | 0.000 | 0.927 |
| 1150 | 0.657 | 0.077 | 0.984 |
| 1200 | 0.831 | 0.379 | 1.000 |
| 1250 | 0.912 | 0.659 | 1.000 |

## Recommended GPU grid

`[600, 650, 700, 750, 800, 850, 900, 950, 1000, 1050, 1100, 1150, 1200]` per hour, 25 minutes each

The load-independent simulation predicts a much lower miss rate at 931/h than the observed 74.7%; the engine's service time grows with batch size and the queue dominates the knee. Use the empirical P1 bracket for the GPU grid, not the simulation as a point predictor.

