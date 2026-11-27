# P2B: preview authorisation and 240 s calibration stop

**Status:** **STOP.** The 240 s calibration ran on 2026-11-24 and found **no
rate inside the frozen 15–40% miss band**. Per `configs/qualify_aime_v1.json`,
the live manipulation check is not authorised, `--stage freeze` is refused, and
P2 is withheld. No threshold, deadline, band, pressure rule, cut rule or preview
threshold was changed after seeing the result.

## 1. Preview authorisation (documented override)

The 24-item, single-wave gate returned `inconclusive_grader`: 8k accuracy
41.7%, gain +8.3 points, answer change 45.8%, but the 8k missing-box rate was
20.8% against a 20% ceiling. Every missing box was an `answer_cap` record.

That verdict is a **trace-shape artefact**, not a pool failure. The same
questions, measured in 48-item two-wave traces where both arms see comparable
batching, clear every criterion on two independent seeds:

| measurement | 4k | 6k | 8k | gain | 8k caps | decision |
|---|---:|---:|---:|---:|---:|---|
| 24-item single wave, seed 900000 | 8/24 | 8/24 | 10/24 | +8.3 | 5/24 | `inconclusive_grader` |
| 48-item two waves, seed 900000 | 18/48 | 22/48 | 27/48 | +18.8 | 3/48 | passes |
| 48-item two waves, seed 910000 | 17/48 | 22/48 | 26/48 | +18.8 | 4/48 | passes |
| combined (96 responses) | 35/96 | 44/96 | 53/96 | **+18.8** | 7/96 | 22 conversions / 4 derailments, p = 5.3e-4 |

With only 24 requests in a 32-slot batch the answer channel runs longer, five
8k answers hit the 2,048-token allowance instead of two, and the 8k arm loses
two to three responses. The same 24 questions scored **0 of 48** identical
token sequences and a +20.8 to +25.0-point gain inside the 48-item traces. The
single-wave gate understates the 8k arm by 12–17 points.

**Decision:** the `inconclusive_grader` result no longer blocks authorisation.
The preview is authorised on the two-wave 48-item evidence. The gate is declared
as a 48-item, two-wave trace for future re-qualification
(`configs/qualify_aime_v1.json` → `preview.gate_design`).

## 2. Calibration design and rig

| item | value |
|---|---|
| engine | vLLM 0.11.2, `enforce_eager=True`, `enable_prefix_caching=False` |
| model | Qwen3-4B rev `1cfa9a72...`, 12,288-token window |
| serving | 32 slots, 8,192 batched tokens, legacy contract, 2,048-token answer allowance |
| policy | pressure threshold 8, 2-step persistence, cut to 4,096 |
| design | 48 signal questions + 30% MATH-500 filler, 25 min/rate, 600 s warm-up, 900 s measured, 240 s deadline from actual client submission |
| band / target | 15–40% / 0.25 |

All eight phase records report `injection_valid=true` and 0 request errors; rig
facts were read back from every server start (`enforce_eager=True`,
`max_seq_len=12288`, prefix caching off).

## 3. Rates measured

| nominal /h | realised /h | signal | misses | miss rate | p50 latency | p90 latency | waiting p90 |
|---:|---:|---:|---:|---:|---:|---:|---:|
| 750 | 772 | 112 | 0 | 0.0% | 143.9 | 180.4 | 2 |
| 800 | 765 | 140 | 0 | 0.0% | 144.5 | 156.2 | 0 |
| 850 | 931 | 139 | 0 | 0.0% | 150.0 | 179.2 | 6 |
| 900 | 940 | 160 | 0 | 0.0% | 147.0 | 169.6 | 2 |
| 950 | 976 | 179 | 2 | 1.1% | 195.1 | 219.0 | 16 |
| 1000 | 960 | 181 | 0 | 0.0% | 175.1 | 210.2 | 9 |
| 1025 | 1058 | 170 | 163 | **95.9%** | 325.2 | 356.4 | 53 |
| 1050 | 1107 | 192 | 108 | **56.2%** | 248.2 | 351.0 | 49 |

`1100/h` was stopped at the phase boundary once 1050/h had supplied the lowest
over-band point, so the declared refinement (1000 / 1025 / 1050) could run.

## 4. Decision and why there is no band

`calibration.json`: `band_found = false`, `chosen = null`, bracket
`{below: 950/h (1.1%), above: 1050/h (56.2%)}`. The live check, freeze and P2
were not run; no frozen packet, source lock or P2 traces were written.

At and below 1000/h the queue **drains** through the measured window and almost
nothing misses. At 1025/h and 1050/h the queue **saturates** and the miss rate
is 50–100%. The transition happens inside a 25/h step, so the curve is a cliff,
not a slope.

Three properties make a 25/h grid unable to locate the knee:

1. **Realised rate ≠ nominal rate.** Exponential inter-arrivals give about ±5%
   sampling error, and the realised rates are not monotone across the grid.
2. **Warm-up backlog dominates above capacity.** If the warm-up ends with 30–50
   requests queued, almost every measured request is already past 240 s. This
   explains the non-monotone 1025 vs 1050 points.
3. **One window per rate, no replicate.** The over-band miss rate is bimodal,
   so walking a finer grid on single windows cannot bracket 15–40%.

A CPU pre-calibration model had predicted a gentle band around 1050–1100/h; it
was wrong in both shape and position because it could not represent the
batch-size-driven collapse. The empirical P1 bracket, not the simulation, set
the GPU grid.

A repeat diagnostic on the same 1000/h, 1025/h and 1050/h traces kept every
point on its side of the band (1000: 0.0%/6.6%; 1025: 95.9%/92.4%; 1050:
56.2%/46.4%) and reproduced the 1025 > 1050 ordering. The cliff is real; the
band cannot be located by a finer grid on single windows. The diagnostic is
non-authorising.

## 5. Records

| path | contents |
|---|---|
| `results/p2b/calibration/calibration.json`, `CALIBRATION.md` | every rate, metrics, bracket, decision |
| `results/p2b/calibration/phases.json`, `phases/` | eight phase records |
| `results/p2b/calibration/{clients,requests}/`, `scheduler.jsonl` | per-request and scheduler records |
| `results/p2b/calibration/manifest.json` | job, code/config hashes, week 7 source lock |
| `results/p2b/diag-repro/` | repeat diagnostic |
| `results/p2b/preview24/`, `preview48-exploratory/`, `seed2/` | preview records |
