# 12. Feasibility notes: the CPU checks behind the plan

No GPU work was run to produce these numbers. They come from saved results in the repository, from
the pinned library versions, and from simple arithmetic/queue simulation. The script
[`feasibility.py`](../feasibility.py) reproduces the tables in sections 3-7 without a GPU.

## 12.1 Environment checked

| Item | Observed | Consequence |
|---|---|---|
| GPU partition | `ice-gpu`, 16 h time limit | The main run must fit one 16 h allocation or be resumable |
| Login node | No GPU, no `nvidia-smi`, no vLLM in the default Python | All GPU work goes through Slurm |
| Serving venv | `/storage/.../LARB-week5-env/venv`, Python 3.11, vLLM 0.11.2, torch 2.9.0, transformers 4.57.6 | The pins match the binder; use this venv |
| Analysis venv | `math-verify 0.9.0` | Grading stack available without the serving venv |
| Model | `/storage/.../LARB-week5-env/model/Qwen3-4B`, 3 safetensors shards, BF16 | Local model, no download needed |
| Network | Hugging Face reachable from the login node | Datasets can be staged before the GPU job |
| HF cache | Qwen3-4B only | New datasets must be downloaded and frozen |

## 12.2 Measured throughput at the old concurrency

The week 5/6 saved records show 220-500 output tokens/s aggregate at two slots, depending on the
phase and the mix; the binder's 80 tokens/s is a per-request figure, not the aggregate. The useful
planning numbers are:

| Quantity | Value | Source |
|---|---:|---|
| Single 8k-token response | about 100 s | binder 1.8 |
| Per-request decode at two slots | about 65-70 tokens/s | week 6 response metrics |
| Aggregate at two slots | about 220-300 tokens/s | week 6 burst/near phases |
| Measured responses per GPU-hour | 25-110, typically 30-60 for AIME | binder 1.8 |

The old rig was not saturating the device: at two sequences, a 4B BF16 model on an H100 should be
able to do more. This is the case for scaling concurrency.

## 12.3 KV cache and concurrency

Qwen3-4B: 36 layers, 8 KV heads, head dim 128, BF16. KV per token:

```
2 (K and V) * 36 * 8 * 128 * 2 bytes = 147,456 bytes/token = 144 KiB/token
```

| Context per request | KV per request | Max sequences at 0.80 util | At 0.85 util | At 0.90 util |
|---:|---:|---:|---:|---:|
| 8,192 | 1.21 GB | 46 | 49 | 52 |
| 12,288 | 1.81 GB | 30 | 33 | 35 |
| 16,384 | 2.42 GB | 23 | 24 | 26 |
| 20,480 | 3.02 GB | 18 | 19 | 21 |
| 24,576 | 3.62 GB | 15 | 16 | 17 |

The table subtracts about 8.2 GB for weights and assumes the whole KV budget is available. In
practice vLLM allocates blocks on demand, so a 32-sequence run with 8.3k-token requests uses about
39 GB of KV, not 32 x 1.81 GB. A 32-way run at 16k thinking would need about 77 GB of KV and does
not fit. This is why the main path uses 8k as "full" and keeps 16k for a lower-concurrency bridge.

## 12.4 Answer phase

From the 232 measured week 6 responses:

| Group | n | p10 | Median | p90 | Max |
|---|---:|---:|---:|---:|---:|
| All answer tokens | 232 | 814 | 1,371 | 2,049 | 2,049 |
| Correct | 81 | 669 | 1,128 | 1,430 | 1,864 |
| Incorrect | 151 | 912 | 1,867 | 2,049 | 2,049 |
| Answer-cap failures | 63 | 2,049 | 2,049 | 2,049 | 2,049 |

The cap rate is 22-33% depending on the arm. A cap is scored wrong. A 512-token answer cap would
catch almost every response, so shortening the allowance without changing the cue is not viable.
A short forced-boxed contract is a genuine rig change and needs the 384-response bridge in
[08-experiment-design.md](08-experiment-design.md), section 8.4.

## 12.5 Power and the question-level ICC

Paired binary power, 80% power, two-sided alpha 0.05, for `n` independent paired units:

| Effect (points) | Discordance 0.10 | 0.15 | 0.20 | 0.25 | 0.30 |
|---:|---:|---:|---:|---:|---:|
| 3 | 873 | 1,309 | 1,745 | 2,181 | 2,617 |
| 4 | 491 | 736 | 982 | 1,227 | 1,472 |
| 5 | 314 | 471 | 628 | 785 | 942 |
| 6 | 219 | 328 | 437 | 546 | 655 |
| 8 | 123 | 184 | 246 | 307 | 368 |
| 10 | 79 | 118 | 157 | 197 | 236 |

The week 6 12-question slice has a question-level ICC of about 0.62-0.79 for `fixed8k`, `fixed4k`
and `live`: most questions are always right or always wrong. That slice is an extreme, selected
set, not a representative cohort. The planning assumption for a broad 200-250-question pool is ICC
0.2-0.4; the upper bound of 0.6 is shown as a sensitivity. Effective pairs for `Q` questions x `m`
seeds:

```
n_eff = Q * m / (1 + (m - 1) * ICC)
```

| Q | m | n_eff at ICC 0.2 | n_eff at ICC 0.4 | n_eff at ICC 0.6 |
|---:|---:|---:|---:|---:|
| 200 | 4 | 500 | 364 | 286 |
| 220 | 4 | 550 | 400 | 314 |
| 246 | 4 | 615 | 447 | 351 |
| 220 | 6 | 660 | 440 | 330 |
| 500 | 4 | 1,250 | 909 | 714 |
| 800 | 4 | 2,000 | 1,455 | 1,143 |

At 0.20 discordance, the 80% MDE is about 5.3-6.3 points for the 220 x 4 main path at ICC 0.2-0.4,
about 7.1 points at the 12-question ICC 0.6 upper bound, and about 3.5-4.2 points for 500
questions. The 800-question extension is about 2.8-3.3 points. This is why the main path claims
5-6 points, not 3.

## 12.6 Queue simulation: load, deadline and the miss band

A simple FIFO multi-server simulation with lognormal service times, 32 servers, and a mixed
workload (55% long, median 150 s; 45% short, median 35 s) shows the expected congestion
transition. The exact numbers will change on the real engine; the shape is the point.

One draw, from `feasibility.py` (12,000 arrivals per cell; exact values vary with the seed):

| Utilisation | Arrivals/hour | Miss@180 | Miss@210 | Miss@240 | Median latency | p90 latency |
|---:|---:|---:|---:|---:|---:|---:|
| 0.70 | 787 | 15% | 7% | 3% | 100 s | 197 s |
| 0.80 | 899 | 15% | 7% | 3% | 101 s | 198 s |
| 0.90 | 1,012 | 18% | 9% | 4% | 106 s | 205 s |
| 0.95 | 1,068 | 22% | 12% | 6% | 116 s | 220 s |
| 1.00 | 1,124 | 64% | 53% | 40% | 217 s | 364 s |
| 1.05 | 1,180 | 94% | 93% | 92% | 1,098 s | 1,603 s |

Two readings matter. First, the system falls off a cliff near 1.0 utilisation; the main run should
sit at 0.90-0.95, not at 1.0. Second, a 180 s deadline at 0.90-0.95 utilisation gives an 18-22%
reference miss rate, inside the 15-40% band. The calibration gate tunes the arrival rate to this
band; the exact rate on the real engine will differ because the service-time distribution and the
scheduler are different.

A separate long-only, higher-variance draw (median 150 s, p90 250 s) at 0.9 utilisation gave 42%
misses at 180 s, 27% at 210 s and 17% at 240 s. The declared SLO and the arrival rate are therefore
a pair; neither is chosen alone.

The simulation does not model cuts. A cut that shortens a request by 30% reduces the mean service
time, which lowers utilisation and can reduce misses; at 0.85-0.9 utilisation the simulated
reduction was small because the queue was already short. The real experiment must measure whether
the quality cost of the cut is worth the queue benefit; the simulation cannot answer that.

## 12.7 Throughput roofline

A rough H100 memory roofline for Qwen3-4B BF16 (weights 8.2 GB, 2.8 TB/s effective bandwidth),
ignoring scheduler overhead:

| Concurrency | Context | KV total | Step time | Aggregate tokens/s |
|---:|---:|---:|---:|---:|
| 2 | 6,000 | 1.8 GB | 3.6 ms | 562 |
| 8 | 6,000 | 7.1 GB | 5.5 ms | 1,466 |
| 16 | 6,000 | 14.2 GB | 8.0 ms | 2,004 |
| 32 | 6,000 | 28.3 GB | 13.0 ms | 2,454 |
| 32 | 8,300 | 39.2 GB | 16.9 ms | 1,892 |
| 48 | 8,300 | 58.7 GB | 23.9 ms | 2,008 |

The measured two-slot aggregate of 220-300 tokens/s is below the 2 x 6k roofline (562), which is
consistent with eager-mode and scheduler overhead. If the scaled engine reaches even half the
32-slot roofline, about 950 tokens/s, the main run is 10-16 h. This is why Gate C is decisive.

## 12.8 Dataset sizes checked

| Pool | Items | Answer format | Note |
|---|---:|---|---|
| `MathArena/aime_2025` | 30 | integer | Bridge only |
| `MathArena/aime_2026` | 30 | integer | Fresh |
| `MathArena/hmmt_feb_2025` | 30 | short expression | Recent |
| `MathArena/hmmt_nov_2025` | 30 | short expression | Fresh |
| `MathArena/hmmt_feb_2026` | 33 | short expression | Fresh |
| `MathArena/smt_2025` | 53 | expression | Recent; some non-integer |
| `MathArena/brumo_2025` | 30 | expression | Recent; some non-integer |
| `MathArena/cmimc_2025` | 40 | expression | Recent; some non-integer |
| **Raw total** | **276** | | **200-246 after QC** |
| `MathArena/aime_2023_I/II` | 30 | integer | Disjoint screen |
| `MathArena/hmmt_feb_2024` | 30 | short expression | Disjoint screen |

The screen uses 24 AIME 2023 + 24 HMMT Feb 2024 = 48 items, disjoint from the main cohort, plus a
24-item preview sampled from the main cohort and excluded from the main analysis. The main cohort is
the 2025-2026 set above. AIME 2025 is the bridge and is not in the main cohort, so the main result
is not a rerun of the project's most-used 30 questions.

## 12.9 What these checks imply

1. **Concurrency is the right first lever.** The old rig was far from the memory roofline; 32 slots
   should multiply data per GPU-hour several-fold.
2. **8k is the serving "full" budget.** 16k at 32 slots does not fit. A 16k bridge is a separate,
   lower-concurrency experiment.
3. **The answer phase is a real cost.** A short answer contract is worth a gate, but it is not free
   to assume; the bridge decides.
4. **The main path is powered for 5-6 points, not 3.** A 220-question cohort at ICC 0.2-0.4 has
   about 400-550 effective pairs; 3 points needs 500-800 questions.
5. **A 180 s SLO at 0.90-0.95 utilisation gives a real miss band.** The calibration gate tunes the
   arrival rate, not the deadline.
6. **A realistic result is achievable in one gate job plus one 16 h main job.** The plan does not
   need a multi-week campaign to produce a decision.

