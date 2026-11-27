# Consolidated serving findings

**Updated:** 2026-11-26. This is the single orientation document for the
scaled-serving thread. The experiment phase is closed: the one-way in-flight
8k→4k cut is not advanced, and the queue-aware admission rule is the best
candidate but is not yet confirmed. The linked result records remain the
evidence.

## 1. Verdict

| Question | Answer | Status |
|---|---|---|
| Does more thinking buy AIME accuracy? | **Yes.** 4k → 8k is +17.2 points over 87 historical paired AIME responses and +18.8 over 96 AIME 2025+2026 responses (p = 5.3e-4). | Established; reuse as the positive control. |
| Does the rig reproduce the AIME slope? | **Yes**, on 48-item two-wave traces on two seeds. The 24-item single-wave gate understates the 8k arm by 12–17 points. | Established; do not use 24-item single-wave previews for the slope. |
| Is there a 15–40% sustained-miss band at 240 s? | **No.** 0–1.1% through 1000/h, 95.9% at 1025/h, 56.2% at 1050/h; the queue is a capacity cliff. | Closed; P2B documented stop. |
| Is there a 15–40% band at 180 s? | **No.** 0% at 800/h, 74.7% at 931/h. | Closed; P1 record. |
| Does the `live` pressure-cut beat `fixed4k` at scale? | **Not confirmed.** P2C reads +4.6 points (below the +5 GO); P3C reads live4k +10.6 over fixed4k but only +0.6 over admission. | Closed; the current cut is not advanced. |
| Is the cut's accuracy cost bounded? | **No.** P2C `live` is 10 points below fixed8k; P3C live4k is 5 points below fixed8k and live6k 6.1 below. | Closed for the current cut. |
| Which policy is best on correct-on-time? | **Admission-only (`arrival`) is the best point estimate but is not confirmed:** 41.7% in P2C, 45.0% in P3C-A, 38.9% in P3D; fixed4k is 34.6%/35.0%/36.1%. P3D reads only +2.8 points over fixed4k (CI [−3.3, +9.4]). | Open; directionally positive but trace-dependent. |
| Does a cut win when it hits a full 8k cohort? | **No overall.** live4k +0.6 points over arrival (CI [−5.0, +5.6]); live6k −1.1. The burst-window gain (+12.9) is paid for by 6–16 cohort accuracy points. | P3C directional stop. |

## 2. Cycle history

| Cycle | Question | Outcome | Status / record |
|---|---|---|---|
| Week 7 P0/P1 | Is the rig valid and is a pool available for a main run? | Rig gates passed (bridge, 32-row mechanics, contract, throughput). The 2025–2026 main cohort failed the slope preview; P2 withheld. Calibration at 180 s was a cliff. | Closed; `week7/scaled-serving/reports/P0-REPORT.md`, `P1-REPORT.md` |
| Week 8 P2A (Omni-MATH) | Can the Omni-MATH hard pool carry a serving comparison? | 24-item preview: 4k 8/24, 6k 8/24, 8k 7/24; gain −4.2 points. Stop before calibration. | Closed; `results/p2a/` |
| Week 8 pool decision | Which pool carries the budget slope? | AIME is the only family with a positive, reproducible 4k→8k effect; `aime-2025-2026-v1` was declared before measurement. | Established; [POOL-DECISION.md](POOL-DECISION.md), [SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md) |
| Week 8 P2B preview | Is the AIME pool authorised? | 24-item single-wave gate was `inconclusive_grader` on a 20.8% missing-box rate; the same questions in 48-item two-wave traces passed on two seeds (+18.8 points each). Documented override. | Closed as authorised; [P2B-CALIBRATION-STOP.md](P2B-CALIBRATION-STOP.md) |
| Week 8 P2B calibration | Is there a 240 s sustained-miss band? | Eight rates, no band. 1000/h → 0.0%, 1025/h → 95.9%, 1050/h → 56.2%. Repeat diagnostic kept each point on its side. | Closed; [P2B-CALIBRATION-STOP.md](P2B-CALIBRATION-STOP.md) |
| Week 8 P2C | Can a controlled burst test the live mechanism and the AIME slope without the rate cliff? | **Inconclusive under the pre-declared rule.** Slope +14.6; live +4.6 vs fixed4k (below +5), live −2.5 vs arrival and −9.5 in the burst window. Arrival best at 41.7%. | Closed; [P2C-RESULT.md](P2C-RESULT.md), `results/p2c/final/` |
| Week 8 P3C | Does a cut win when a 64-request burst hits a full 32-request 8k cohort, and can a 6k cut preserve accuracy? | **Inconclusive under the +5 rule; directional stop for the cut.** live4k +0.6 vs arrival; live6k −1.1. Cut recovers +12.9 in the burst window but loses 6–16 cohort accuracy points. | Closed; [P3C-PREFILL-RESULT.md](P3C-PREFILL-RESULT.md), `results/p3c/final/` |
| Week 8 P3D | Does the admission effect replicate on an independent B trace? | **Direction repeats, magnitude does not.** arrival 38.9% vs fixed4k 36.1%; +2.8 points (CI [−3.3, +9.4]), not the P3C +10.0. | Closed; [P3D-ADMISSION-RESULT.md](P3D-ADMISSION-RESULT.md), `results/p3d/` |

## 3. What is established

1. **The rig and contract work.** vLLM 0.11.2, Qwen3-4B rev `1cfa9a72...`,
   32 slots, 8,192 batched tokens, 12,288 window, eager, no prefix caching,
   legacy contract with a 2,048-token answer allowance. The P1 bridge and
   mechanics gates passed; every calibration phase had 0 request errors.
2. **AIME carries the budget slope.** The effect survives exclusion of
   answer-capped responses, survives the 2,048-token answer allowance, and
   repeats on a second seed at 48 items. It is a family property, not a rig
   artifact.
3. **The AIME 2025+2026 pool is usable.** 60 items (30 fresh AIME 2026, 30
   exposed AIME 2025), all integer-answer, self-gradable and context-safe.
   Maximum prompt 767 tokens; 1,265-token margin at the frozen 8k shape.
4. **Capacity is about 1,000–1,100 requests/hour on this rig.** Service time is
   roughly 150–170 s per 8k signal, 80–90 s per 4k signal and 22–25 s per 1k
   filler. The 32 slots are nearly full at 1000/h and over capacity at 1025/h.
   The 240 s deadline is not the binding constraint; capacity is.
5. **The AIME slope survives a controlled burst.** P2C measures +14.6 points
   from 4k to 8k over 240 paired responses (39 conversions vs 4 derailments,
   p ≈ 3e−6). The slope is a reliable positive control.
6. **Admission-only is the best point estimate on correct-on-time.** P2C:
   `arrival` 41.7%, `live` 39.2%, `fixed8k` 37.9%, `fixed4k` 34.6%; paired
   `arrival` − `fixed4k` +7.1 points (CI [+2.9, +11.7]). P3C repeats the
   direction (+10.0), P3D weakens it (+2.8).
7. **The one-way 8k→4k cut does not add goodput and costs accuracy.** In P2C
   `live` is 2.5 points below `arrival` overall and 9.5 below it in the burst
   window. In P3C, even against a full running cohort, the best live arm ties
   admission (+0.6) while losing 15.6 cohort accuracy points; the 6k target
   loses 6.3 and still does not win.

## 4. What is not established

- **The magnitude of the admission effect.** P2C +7.1, P3C-A +10.0 and P3D
  +2.8 versus fixed4k; the P3D interval [−3.3, +9.4] includes zero. Do not
  quote +10.0 as the effect. A powered, multi-trace replication is required.
- **Whether the cut helps in a value/deadline-asymmetric setting.** Every test
  here used equal-value requests on the same 240 s deadline. Cutting
  low-value or loose-deadline background work to protect a foreground burst is
  the remaining untested case; it needs a new pre-declaration.
- **Generalization beyond this setup.** One model (Qwen3-4B), one H100, one
  block, a small number of traces. The burst result is not a general
  service-load result.

## 5. Why the sustained-rate cycle stopped

P2B tried to find a sustained arrival rate whose reference-arm miss rate was
15–40% at 240 s. The rig has a hard capacity ceiling: at 1000/h the queue
drains (0% miss, 30 of 32 slots needed); at 1025/h the queue grows (95.9%
miss). The transition happens inside a 25/h step, and realised arrivals carry
about ±5% sampling error, so a 25/h grid cannot resolve the knee. The
non-monotone 1025 vs 1050 points come from the warm-up backlog. A repeat
diagnostic kept every point on its side of the band, confirming a reproducible
cliff rather than a bad draw. No deadline, band, threshold or cut rule was
changed after the result. P2C replaced the sustained-rate search with a
controlled burst, holding every rig parameter fixed.

## 6. Results at a glance

**P2C burst pilot** (240 signal responses/arm; accuracy / correct-on-time):

| arm | accuracy | correct-on-time |
|---|---:|---:|
| fixed4k | 34.6% | 34.6% |
| fixed8k | 49.2% | 37.9% |
| arrival | 41.7% | 41.7% |
| live | 39.2% | 39.2% |

Slope +14.6; `live` − `fixed4k` +4.6 (CI [+0.8, +8.3], below the +5 GO);
`live` − `arrival` −2.5 overall and −9.5 in the burst window.

**P3C prefilled-cohort cut stress** (180 signal responses/arm):

| arm | accuracy | correct-on-time | burst-window correct-on-time | cohort accuracy |
|---|---:|---:|---:|---:|
| fixed4k | 35.0% | 35.0% | 25.8% | 37.5% |
| fixed6k | 39.4% | 38.3% | 19.4% | 46.9% |
| fixed8k | 50.6% | 43.3% | 6.5% | 62.5% |
| arrival | 46.1% | 45.0% | 9.7% | 59.4% |
| live4k | 45.6% | 45.6% | 22.6% | 43.8% |
| live6k | 44.4% | 43.9% | 22.6% | 53.1% |

`live4k` − `arrival` +0.6 (CI [−5.0, +5.6]); `live6k` − `arrival` −1.1. The cut
buys about 13 burst-window points and pays with 6–16 cohort accuracy points.

**P3D independent admission replication** (180 signal responses/arm):

| arm | accuracy | correct-on-time |
|---|---:|---:|
| fixed4k | 36.1% | 36.1% |
| fixed6k | 38.9% | 33.9% |
| fixed8k | 47.2% | 35.6% |
| arrival | 42.8% | 38.9% |

`arrival` − `fixed4k` +2.8 (CI [−3.3, +9.4]): direction repeats, magnitude does
not.

## 7. Decision and next action

The one-way cut is closed. Do **not** spend a confirmatory block on it: P2C is
below its +5 GO, and P3C shows that even in the cut's best natural case the best
live arm ties admission while losing cohort accuracy. The cut redistributes
burst-window timeliness; it does not improve goodput.

Admission remains the best candidate, but it is **not confirmed**. The three
estimates are +7.1, +10.0 and +2.8, and the newest interval includes zero. The
next useful pre-declaration is a **powered, multi-trace admission replication**
with more questions and seeds; `arrival` versus fixed4k/fixed6k/fixed8k remains
the comparison, with fixed4k as the real competitor.

The only cut design worth revisiting is a **value/deadline-aware** one: a
background cohort on a loose deadline or lower value, a foreground burst on the
240 s deadline, foreground correct-on-time as primary and background accuracy as
a guardrail. Selective/late cuts and a three-level 8k/6k/4k admission rule are
the clean follow-ups; they require a new pre-declaration.

## 8. Measurement notes

- **Cut-after-close is a strict `>` test.** A cut at exactly `cue_start` is the
  boundary cut and is not counted as after-close.
- **`worker.jsonl` is the authoritative cut stream.** The frozen controller
  persists request state before appending the cut event, so a request record's
  cut list can be empty even when a cut was applied.
- **Caps, late answers, missing outputs and errors stay in the denominator.**
- **The 24-item single-wave gate is biased, not merely noisy.** It understates
  the 8k arm by 12–17 points; use 48-item two-wave traces.

## 9. Record map

| Topic | Record |
|---|---|
| Week 7 P0 CPU rig, datasets, protocol | `week7/scaled-serving/reports/P0-REPORT.md`, `results/p0/` |
| Week 7 P1 GPU gates, 180 s calibration, pool stop | `week7/scaled-serving/reports/P1-REPORT.md`, `results/p1/` |
| Family slope analysis and AIME pool | [SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md), [POOL-DECISION.md](POOL-DECISION.md) |
| P2B preview authorisation and 240 s stop | [P2B-CALIBRATION-STOP.md](P2B-CALIBRATION-STOP.md), `results/p2b/` |
| **P2C burst pilot** | [P2C-RESULT.md](P2C-RESULT.md), `configs/p2c_burst_pilot.json`, `results/p2c/final/` |
| **P3C prefilled-cohort cut stress** | [P3C-PREFILL-RESULT.md](P3C-PREFILL-RESULT.md), `configs/p3c_prefill.json`, `configs/p3c_live6k_fixed.json`, `results/p3c/final/` |
| **P3D admission replication** | [P3D-ADMISSION-RESULT.md](P3D-ADMISSION-RESULT.md), `configs/p3d_admission.json`, `results/p3d/` |
| Raw Omni-MATH stop record | `results/p2a/`, `configs/pool_omni.json` |
| Generated per-run decisions and tables | `results/*/PILOT.md`, `results/*/PREFILL.md` |

