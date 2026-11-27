# P3D independent admission replication

**Status:** pre-declared and completed 2026-11-26. Authoritative generated output
is `results/p3d/prefill.json` and `PREFILL.md`; frozen config is
`configs/p3d_admission.json`.

## Question and design

P3C made the queue-aware admission rule the reproducible effect: `arrival` was
+10.0 points over fixed4k (CI [+2.2, +18.3]) and +6.7 over fixed6k on
correct-on-time, while the cut only tied admission. P3D replicates the admission
comparison on the independent B trace.

- trace: `artifacts/traces-candidates/p3c-prefill-b.jsonl` (32-request 8k
  cohort, 64-request burst, 162-request tail; 180 signal / 78 filler; 240 s
  deadline).
- arms: `fixed4k`, `fixed6k`, `fixed8k`, `arrival`; no cut arm.
- 180 signal responses/arm (60 questions × 3 seeds), 258 requests/phase.
- frozen rig, threshold 8 / 2-step persistence, one server group.

The primary read-out is `arrival` minus each fixed arm on correct-on-time with
the same paired question-level arithmetic as P2C/P3C. This is a replication, not
a powered P3: the 180/arm MDE is roughly 12–16 points. No new GO/STOP threshold
was introduced.

## Result

All four phases are present with 0 missing outputs and 0 errors; fixed arms made
no cuts. The generated decision label is `admission_only`.

| arm | accuracy | correct-on-time | on-time | caps |
|---|---:|---:|---:|---:|
| fixed4k | 36.1% | 36.1% | 98.3% | 33 |
| fixed6k | 38.9% | 33.9% | 85.6% | 23 |
| fixed8k | 47.2% | 35.6% | 71.1% | 23 |
| arrival | 42.8% | 38.9% | 87.8% | 35 |

Paired question-level differences (60 units):

| comparison | correct-on-time | 95% CI | accuracy |
|---|---:|---|---:|
| arrival − fixed4k | +2.8 | [−3.3, +9.4] | +6.7 |
| arrival − fixed6k | +5.0 | [−0.6, +11.1] | +3.9 |
| arrival − fixed8k | +3.3 | [−1.1, +7.8] | −4.4 |

## Interpretation

The **direction repeats, but the magnitude does not**. P2C read admission −
fixed4k at +7.1 and P3C-A at +10.0; P3D reads +2.8 with an interval that
includes zero. In P3D, fixed4k is nearly on-time (98.3%) and only 2.8 points
below arrival on correct-on-time, while arrival has more misses (12.2% vs 1.7%).
The arrival advantage is carried by accuracy, not timeliness, and is not big
enough at this sample size to separate from fixed4k.

The burst window is not a clean admission win either: fixed4k 38.5%
correct-on-time versus arrival 20.5%; cohort: fixed8k 46.9%, arrival 37.5%,
fixed4k 25.0%. Trace-to-trace variation in the burst/cohort mix is large
relative to the 180/arm effect. This is a useful negative replication, not
grounds to declare admission confirmed or refuted.

## Decision and next step

No policy is advanced on P3D. The cut remains closed (P3C). Admission remains
the best candidate by point estimate but is **not confirmed**: the three
estimates are +7.1, +10.0 and +2.8, with the newest interval crossing zero. The
next cycle should increase questions/seeds and use multiple independent traces
before spending a confirmatory block. Do not present +10.0 as the reproducible
magnitude.

## Limits

- 180 responses/arm, 60 question units; MDE ~12–16 points; a screening
  replication, not a powered P3.
- The B trace has 39 signal/25 filler in the burst and 109 signal/53 filler in
  the tail, versus A's 31/33 and 117/45.
- Caps, late answers and errors stay in the denominator.
- P3D does not change the frozen P2C/P3C records; it is a new independent trace.

## Records

`results/p3d/prefill.json`, `PREFILL.md`, `summary.json`, `paired.csv`;
`configs/p3d_admission.json`; trace manifest
`artifacts/traces-candidates/manifest-p3c.json`.
