# Week 8

Week 8 completed the serving-qualification thread. The experiment phase is
closed: the one-way in-flight 8k→4k cut is **not advanced**, and the queue-aware
admission rule is the best candidate but is **not yet confirmed**.

The full record starts at
[scaled-serving/README.md](scaled-serving/README.md) and
[scaled-serving/reports/CONSOLIDATED-FINDINGS.md](scaled-serving/reports/CONSOLIDATED-FINDINGS.md).

## What was learned

- **More thinking buys AIME accuracy.** The 4k→8k slope is +17.2 points over 87
  historical paired AIME responses, +18.8 over 96 AIME 2025+2026 responses
  (p = 5.3e-4), and +14.6 under controlled burst load. It is a family property,
  not a rig artifact.
- **The rig has a capacity cliff, not a tunable miss band.** At 240 s the queue
  drains through 1000/h (0–1.1% miss) and saturates at 1025/h (95.9%), with no
  15–40% sustained-rate band.
- **Admission-only (`arrival`) is the best correct-on-time policy by point
  estimate** in P2C (41.7%) and P3C (45.0%), but the effect is not confirmed:
  the independent P3D replication is only +2.8 points over fixed4k
  (CI [−3.3, +9.4]).
- **The in-flight cut does not beat admission overall.** It recovers about 13
  burst-window points in its best natural case but pays with 6–16 cohort
  accuracy points; the overall result is a tie (+0.6 for live4k) or a loss
  (−1.1 for live6k).

## Closed cycles

| Cycle | Outcome | Record |
|---|---|---|
| P2A (Omni-MATH) | Stopped at the 24-item preview (−4.2-point slope) | [POOL-DECISION.md](scaled-serving/reports/POOL-DECISION.md), `scaled-serving/results/p2a/` |
| P2B (AIME preview + 240 s calibration) | Preview authorised; no 15–40% band, so P2 withheld | [P2B-CALIBRATION-STOP.md](scaled-serving/reports/P2B-CALIBRATION-STOP.md) |
| P2C (quality-first burst) | `inconclusive`; admission best; cut negative vs admission | [P2C-RESULT.md](scaled-serving/reports/P2C-RESULT.md) |
| P3C (prefilled-cohort cut stress) | `inconclusive`, directional stop for the cut | [P3C-PREFILL-RESULT.md](scaled-serving/reports/P3C-PREFILL-RESULT.md) |
| P3D (admission replication) | Direction repeats, magnitude does not | [P3D-ADMISSION-RESULT.md](scaled-serving/reports/P3D-ADMISSION-RESULT.md) |

## Limits to carry into a write-up

- One model (Qwen3-4B), one H100, one block; no 3-point claim.
- 30 of the 60 AIME items are `exposed` (AIME 2025) and 30 are `fresh` (AIME
  2026); report the halves separately.
- 12 items were never used in the preview; report them as the unseen subset.
- Capped, late, missing or unparseable responses stay in the denominator.
