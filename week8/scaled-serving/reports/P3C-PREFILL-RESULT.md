# P3C prefilled-cohort cut stress

**Status:** complete 2026-11-26. Pre-declared before the run; authoritative
combined decision and tables in `results/p3c/final/PREFILL.md` and
`prefill.json`. The pre-declared decision is **`inconclusive`**; the substantive
conclusion is a **directional stop for the current cut**.

## Why this test

P2C's ordinary burst did not have a full running cohort, so admission-only could
handle it and the cut's accuracy cost dominated. P3C tests the one structural
case where a cut has a genuine advantage: all 32 slots are occupied by 8k
requests when a burst arrives. Admission cannot shorten those requests; a cut
can. If a cut cannot win here, advancing the current one-way cut is hard to
justify.

## Design and pre-declared rule

| item | value |
|---|---|
| pool | all 60 `aime-2025-2026-v1` items, 3 seeds/question, 30% MATH-500 filler |
| trace | 32 signal requests at t≈0 fill all 32 slots at 8k; 64 requests at 4/s from t=10 s; 162 tail requests every 6 s from t=120 s |
| arms | `fixed4k`, `fixed6k`, `fixed8k`, `arrival`, `live4k`, `live6k` |
| cut targets | live4k = 4,096; live6k = 6,096; fixed arms no cuts |
| requests | 258/phase: 180 signal (60 questions × 3 seeds) + 78 filler |
| SLO / rig | 240 s deadline; frozen rig, pressure threshold 8 / 2-step persistence, one-way cut semantics |

**Hypotheses.** H-A: admission beats fixed4k and fixed6k sits between 4k and 8k
in accuracy. H-B: a cut beats admission on correct-on-time when the burst hits a
full 8k cohort. H-C: the 6k cut loses less accuracy than the 4k cut while
keeping most of the timeliness gain. H-D: the central claim requires the best
live variant to beat admission by ≥5 points and stay within 5 of arrival
accuracy and 10 of fixed8k accuracy.

**Decision.** GO (`go_cut`) if the best live variant is ≥+5 over `arrival` on
correct-on-time, its accuracy is ≥ arrival −5 and ≥ fixed8k −10. STOP if no live
variant beats arrival on correct-on-time, or both live variants are >10 points
below arrival on accuracy, or validity fails. Otherwise **inconclusive**. This
is a screening extension; 180 responses/arm gives roughly a 12–16-point MDE.

## Results

Valid combined run: the five completed A phases plus the corrected live6k
rerun. 180 signal responses/arm, 0 missing outputs and 0 request errors. Both
live arms made 32 cuts, none after close; fixed arms made none.

| arm | accuracy | correct-on-time | on-time | caps | cuts |
|---|---:|---:|---:|---:|---:|
| fixed4k | 35.0% | 35.0% | 100.0% | 36 | 0 |
| fixed6k | 39.4% | 38.3% | 91.1% | 32 | 0 |
| fixed8k | 50.6% | 43.3% | 76.7% | 17 | 0 |
| arrival | 46.1% | 45.0% | 88.9% | 31 | 0 |
| live4k | 45.6% | 45.6% | 100.0% | 28 | 32 |
| live6k | 44.4% | 43.9% | 98.3% | 26 | 32 |

**Window decomposition** (the important part):

| window | fixed4k | fixed6k | fixed8k | arrival | live4k | live6k |
|---|---:|---:|---:|---:|---:|---:|
| burst correct-on-time (31 signal) | 25.8% | 19.4% | 6.5% | 9.7% | 22.6% | 22.6% |
| cohort accuracy (32 signal) | 37.5% | 46.9% | 62.5% | 59.4% | 43.8% | 53.1% |
| tail accuracy (117 signal) | 36.8% | 41.0% | 52.1% | 50.4% | 52.1% | 47.0% |

The cut does what the structural argument predicts **inside the burst**: it
recovers about 13 points over admission. It pays for that by cutting the running
cohort's accuracy: 43.8% for the 4k cut and 53.1% for the 6k cut versus 59.4%
for admission. The 6k target is less destructive but still does not beat
admission.

**Key paired differences** (question level, 60 units):

| comparison | mean diff | 95% CI |
|---|---:|---|
| arrival − fixed4k (P3C-A) | +10.0 | [+2.2, +18.3] |
| arrival − fixed6k (P3C-A) | +6.7 | [+1.1, +12.8] |
| live4k − arrival | +0.6 | [−5.0, +5.6] |
| live6k − arrival | −1.1 | [−7.8, +5.6] |
| live4k − fixed4k | +10.6 | [+3.9, +17.8] |

The cut beats a fixed short budget, but admission captures the same gain
without cutting. The P3C-A admission − fixed4k magnitude did not replicate in
P3D (+2.8; CI [−3.3, +9.4]).

## Decision

**Pre-declared decision: `inconclusive`.** Validity passes: all six arms are
present, both live arms made 32 cuts, both admitted 4,096 and 8,192 requests, no
cut occurred after close, and fixed arms made no cuts. The best live variant is
live4k at +0.6 points over arrival on correct-on-time, which is inside the
between-stop-and-GO band.

**Directional conclusion: do not advance the current cut.** The point estimate
is +0.6 with an interval spanning zero, and live6k is 1.1 points below arrival.
The cut is not a candidate for a confirmatory block on a homogeneous 240 s AIME
workload. The conditional P3C-B run was not started.

The rule did not fire `stop_cut` only because live4k's point estimate is
slightly above arrival. Treating that as a GO would confuse a tie with a win.

## Interpretation

The cut works as a **burst-window redistribution mechanism**, not as a free
improvement. It frees the 32 in-flight 8k requests, recovering about 13 points
of burst-window correct-on-time relative to admission, but it pays with cohort
accuracy. The overall equal-weight endpoint nets out to a tie or a small loss.
The 6k comparison resolves a design question: a gentler cut is less destructive
in the cohort window (53.1% vs 43.8%) and nearly as timely, but still does not
beat admission. The problem is not that 4k is "too aggressive"; admission
already gets the timeliness gain on new arrivals without cutting the cohort.

The static arms are informative. fixed8k has the highest eventual accuracy
(50.6%) and cohort accuracy (62.5%), but 23.3% of signal misses the deadline.
fixed4k is 100% on-time but only 35.0% accurate. Admission is the best
equal-weight operating point, and live4k ties it while making 32 cuts.

A cut could still be justified if the cohort requests were lower-value or had
looser deadlines than the burst, i.e. if cutting them is a deliberate priority
decision rather than an accuracy loss on equal-value work. That is the next
hypothesis to pre-declare, not a reason to rerun the current cut.

## Next step

Do not spend a confirmatory block on the current one-way cut. The next useful
cycle is a **powered, multi-trace admission replication**, not another cut.
P3D shows the 180/arm admission effect is too small and trace-dependent for a
single-block confirmation. A cut experiment is worth revisiting only with an
explicit value/deadline asymmetry (background cohort on a loose deadline or low
value, foreground burst on the 240 s deadline).

## Limits

- Screening extension, not a powered P3: 180 responses/arm gives roughly a
  12–16-point MDE at ICC 0.2–0.6. A null is not proof of no effect.
- The original live6k phase was aborted before completion when its engine-core
  process was found cutting to 4,096 instead of 6,096. A startup
  `sitecustomize.py` now propagates `LARB_CUT_TARGET` to every process; the
  corrected single-arm rerun cut all 32 cohort requests to 6,096 and is the only
  live6k data in the combined result. The invalid phase is excluded, not pooled.
- The prefilled cohort is the most favorable natural case for a cut, not a
  representative service load.
- One model, one H100, one block; 60 questions is a coarse comparison.
- Caps, late answers, missing outputs and errors stay in the denominator; cut
  counts use `worker.jsonl`.

## Records

| path | contents |
|---|---|
| `results/p3c/prefill/` | five valid A phases and raw records |
| `results/p3c/live6k-fixed/` | corrected single-arm live6k rerun at 6,096 |
| `results/p3c/final/` | authoritative combined six-arm analysis and decision |
| `configs/p3c_prefill.json`, `configs/p3c_live6k_fixed.json` | frozen configs |
| `artifacts/traces-candidates/p3c-prefill.jsonl`, `manifest-p3c.json` | hashed trace and manifest |

