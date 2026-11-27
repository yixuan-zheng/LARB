# P2C quality-first burst pilot

**Status:** complete 2026-11-24. Decision **`inconclusive`** under the
pre-declared rule. The authoritative generated decision and tables are in
`results/p2c/final/PILOT.md` and `pilot.json`; the frozen thresholds are in
`configs/p2c_burst_pilot.json`.

## Why this cycle

P2B could not find a sustained arrival rate with a 15–40% miss rate: the rig
drains at ≤1000/h and saturates at ≥1025/h. P2C keeps every rig parameter and
the 240 s SLO but replaces the sustained grid with a controlled burst. It uses
the AIME 4k→8k slope as a positive control and as the quality endpoint.

## Design (pre-declared)

| item | value |
|---|---|
| pool | all 60 `aime-2025-2026-v1` items; 30% MATH-500 filler |
| arms | `fixed4k`, `fixed8k`, `arrival` (admission-only), `live` (in-flight cut) |
| trace | 600/h baseline for 420 s, 64 requests at 4/s for 16 s, 600/h recovery |
| traces | A (seed base 920000) and B (seed base 930000) |
| requests | 172/phase: 120 signal (60 questions × 2 seeds) + 52 filler |
| signal | 120/arm after Stage A; 240/arm after Stage B |
| rig | vLLM 0.11.2, Qwen3-4B, 32 slots, 8,192 batched tokens, 12,288 window, eager, legacy 2,048-token answer contract, threshold 8 / 2-step persistence, cut to 4,096 |
| SLO | 240 s from actual client submission |

**Endpoints.** Primary: correct-on-time signal responses (normal completion,
correct safe-normalised answer, receipt ≤240 s). Co-primary: eventual accuracy.
Secondary: burst-window correct-on-time, cap rate, thinking tokens, cuts,
pressure, admission split, fresh/exposed subsets.

**Decision rule.** GO requires validity, 4k→8k slope ≥ +8 points,
`live` − `fixed4k` ≥ +5 on both correct-on-time and accuracy, and `live`
accuracy within 15 points of `fixed8k`. STOP if validity fails, the slope does
not reproduce, `live` is not above `fixed4k` on correct-on-time, or `live`
accuracy falls below `fixed4k` or more than 15 points below `fixed8k`.
Otherwise **inconclusive**. Stage A (trace A) is a screen: it continues only if
the slope is ≥ +8 and `live` is not materially worse than the comparators.

## Results

Stage A passed every continuation screen. Both traces then completed: 8 phases,
1,376 clients, 0 injection failures, 1 request-level client write error
(fixed4k, retained in the denominator). 48 worker cuts, 0 after close, both
4,096 and 8,192 admissions, 0 cuts in the fixed arms.

| arm | correct / 240 | accuracy | correct-on-time | on-time rate | caps |
|---|---:|---:|---:|---:|---:|
| fixed4k | 83 | 34.6% | 83 | 34.6% | 61 |
| fixed8k | 118 | 49.2% | 91 | 37.9% | 25 |
| arrival | 100 | 41.7% | 100 | 41.7% | 40 |
| live | 94 | 39.2% | 94 | 39.2% | 53 |

**Slope.** 4k→8k accuracy +14.6 points (39 conversions vs 4 derailments,
p ≈ 3e−6). The AIME control works under burst load.

**Key paired comparisons** (question level, 240 responses/arm):

| comparison | field | mean diff | 95% CI | sign p |
|---|---|---:|---|---:|
| arrival − fixed4k | correct-on-time | +7.1 | [+2.9, +11.7] | 0.0034 |
| live − fixed4k | correct-on-time | +4.6 | [+0.8, +8.3] | 0.061 |
| live − arrival | correct-on-time | −2.5 | [−6.3, +0.8] | 0.327 |
| live − fixed8k | accuracy | −10.0 | [−16.3, −4.6] | 5.2e−4 |
| live − fixed8k | correct-on-time | +1.3 | [−4.2, +6.7] | 1.0 |

**Burst window** (87 signal responses/arm), the mechanism test:

| arm | correct / 87 | accuracy | correct-on-time |
|---|---:|---:|---:|
| fixed4k | 30 | 34.5% | 30 |
| fixed8k | 38 | 43.7% | 28 |
| arrival | 30 | 34.5% | 30 |
| live | 25 | 28.7% | 25 |

`live` is −9.2 points versus `fixed4k` and −9.5 versus `arrival` inside the
burst window. Its overall +4.6 versus `fixed4k` comes from pre/post-burst
requests admitted at 8k; in the pressure window the cut shortens answers
without recovering misses that admission already avoids.

## Decision

**`inconclusive`**, not GO:

- validity passes (coverage, injection, 48 cuts, 0 after close, both budgets,
  0 fixed-arm cuts);
- slope passes (+14.6, far above the +8 floor);
- `live` − `fixed4k` is **+4.6**, just below the +5 GO and above the stop floor;
- `live` is **−2.5** versus `arrival`, so H2 (the cut adds value beyond
  admission) is not supported; the burst-window estimate is −9.5;
- `live` is **−10.0** versus `fixed8k` on eventual accuracy and only +1.3 on
  correct-on-time (CI includes zero).

The clear positive is admission-only: `arrival` − `fixed4k` is +7.1 points
(CI [+2.9, +11.7]). The cut gives back about 2.5 points overall and 9.5 in the
burst window. The correct action is to stop this cycle, not to move the +5
threshold or spend the confirmatory block on the current cut design.

## Interpretation

- **The AIME slope is a usable positive control under burst load.** The fact
  that works is the budget effect, not the cut.
- **Admission-only is the best policy in this pilot.** The queue-aware 4k
  admission rule carries the measurable gain.
- **The in-flight cut does not add value and costs accuracy.** It is 2.5 points
  below admission overall and 9.5 below it in the burst window at essentially
  identical on-time rates.
- **Full thinking is accurate but late.** `fixed8k` is 14.6 points more accurate
  than `fixed4k`, but only 69.6% of responses finish inside 240 s; its
  correct-on-time rate is 37.9%, no better than admission.
- This is a screening pilot, not a powered P2. The planned MDE is about 10–14
  points; the +4.6 estimate is below that resolution and below the GO
  threshold.

## Limits

- One model, one H100, one block; 60 questions is a coarse comparison.
- Half the AIME items are exposed (AIME 2025); report fresh and exposed halves
  separately.
- Request-record cut lists can omit a cut; counts and the after-close audit use
  `worker.jsonl`.
- A null or inconclusive result does not prove the mechanism has no effect.

## Records

| path | contents |
|---|---|
| `results/p2c/pilot/` | combined Stage A + Stage B run: `pilot.json`, `PILOT.md`, `summary.json`, `paired.csv`, raw records, scheduler/worker streams |
| `results/p2c/stage_a/` | frozen Stage A snapshot (predates the worker-cut audit; use `final/` for cut counts) |
| `results/p2c/final/` | authoritative final snapshot |
| `results/p2c/pilot/pilot-manifest.json` | job, config, trace and code hashes |
| `configs/p2c_burst_pilot.json` | frozen thresholds and trace parameters |

