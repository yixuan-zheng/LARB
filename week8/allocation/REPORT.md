# Week 8 | Question-aware allocation replay

**Verdict: stop.** Extending at the 4K checkpoint by measured per-question continuation value delivered fewer correct-on-time answers than extending by a constant value. The primary difference was **−29 good answers (95% interval −52 to −2)**, and it was negative in 10 of 11 sensitivity cells. The rule was frozen in [PROTOCOL.md](PROTOCOL.md) (commit `6695357`) before any outcome was computed, and nothing changed after.

## Setup

A CPU replay of the burst trace at **540 requests/h** (1,229 arrivals, 137 min) on 32 slots, with P1.3 decode rates and a **240 s deadline** from arrival. Each request is one of the 58 Experiment 2 prefixes and carries one recorded short draw and one recorded long draw; the checkpoint decision picks which one it gets. Every checkpoint rule extends iff **v > λ × waiting ÷ 32**, with λ = 8.69 so the constant rule extends only while nobody waits. Question-aware uses the p8 − p4 of the same question's *other* prefix, so no request is scored on the draws that set its value.

## Main result

| Policy | Good | Per min | Correct | On time | Extended | Tokens | p50 / p90 latency |
|---|---:|---:|---:|---:|---:|---:|---:|
| **Constant** | **545** | 3.99 | 583 | 1,123 | 86% | 10.57M | 151 / 198 s |
| Arrival-only | 535 | 3.92 | 583 | 1,095 | 87% | 10.61M | 152 / 252 s |
| **Question-aware** | **516** | 3.78 | 551 | 1,128 | 28% | 8.11M | 92 / 193 s |
| Fixed 8K | 457 | 3.35 | 606 | 930 | 100% | 11.16M | 156 / 470 s |
| Shuffled control, 20 seeds | 453 (426–486) | | | | 28–29% | | |
| Fixed 4K | 413 | 3.02 | 441 | 1,139 | 0% | 6.82M | 83 / 187 s |
| In-sample ceiling | 556 | 4.07 | 591 | 1,128 | 28% | 8.11M | 92 / 192 s |

| Endpoint | Result | Condition |
|---|---|---|
| Primary: question-aware − constant | **−29**, 95% [−52, −2] | (a) fails; point ≤ 0 means stop |
| Positive in all 11 cells | 1 of 11 | (b) fails |
| Selection: question-aware − shuffled | **+62.9**, 95% [+3.6, +133.4] | (c) passes |
| Fixed check: question-aware − fixed 8K | **+59** | (d) passes |
| Serving go/no-go | not needed | (e) cannot change a stop |

## Why constant wins

- **The values carry information.** With the same number of extensions, choosing by value instead of at random gains 63 good answers. The interval excludes zero, though with 29 questions it is wide.
- **Extending is almost free at this load.** Constant extends three times as often, yet it is on time for 1,123 requests against 1,128. Question-aware gives up 32 correct answers to gain 5 on-time ones.
- **The losses sit where a question's two prefixes disagree.** 22 questions tie, 2 gain (+3 requests) and 5 lose (−32). The largest losses are `aime2026-024` (−10), `007` (−9), `022` (−7) and `011` (−4). In each, one prefix had value 0 or below, so the other was never extended, but it would have benefited. Sixteen questions have value 0 on both prefixes, so question-aware never extends them and loses nothing there. One prefix's value is a noisy guide to another start on the same question.
- **The headroom is small.** Ranking each request by its own draws, which no predictor can do, reaches 556: only **+11** over constant.

## Sensitivity

| Cell | Primary | 95% interval | Selection | Fixed check |
|---|---:|---:|---:|---:|
| Rate ×0.9 (486/h) | −29 | [−55, −4] | +62.9 | +29 |
| Rate ×1.1 (594/h) | −21 | [−53, −1] | +63.9 | +102 |
| Speed ×0.75 | **+7** | [−21, +48] | +57.6 | +96 |
| Speed ×1.25 | −32 | [−59, −5] | +65.9 | +8 |
| Lag 5 s | −27 | [−52, −1] | +62.9 | +59 |
| Lag 20 s | −27 | [−52, −2] | +63.1 | +59 |
| Deadline 180 s | −28 | [−57, −5] | +64.1 | +56 |
| Seed 8223 | −28 | [−57, −4] | +61.1 | +52 |
| Seed 8224 | −20 | [−53, 0] | +69.1 | +60 |
| Seed 8225 | −23 | [−53, −2] | +69.6 | +59 |
| Seed 8226 | −31 | [−56, −3] | +56.3 | +49 |
| Seed 8227 | −22 | [−55, −3] | +65.5 | +53 |

The only positive cell is the 25% slower server. There, fixed 8K collapses to 54 good answers and constant's p90 latency reaches 320 s, so extending less starts to pay. Its interval spans zero.

Context runs, outside the sign rule:

- **Sustained trace at 540/h.** No policy misses a deadline, so only correctness counts. The primary is −29, selection is +75, and fixed 8K (606) beats question-aware (568) by 38.
- **λ sweep.** Moving the anchor to 1, 2, 4 or 8 waiting gives −29, −29, −27 and −28. The result does not depend on the frozen λ.

## Cost

| | Question-aware | Constant |
|---|---:|---:|
| Generated tokens per request | 6,596 | 8,599 |
| Slot-seconds per request | 102 | 139 |

Question-aware saves **2,003 tokens per request** (23%) and 27% of slot time. Building the value table cost 6.93M served-token equivalents, **238,864 per question**. It would take **119 requests per question** for the savings to repay the table, and that is before counting the 29 lost good answers. A new question pays the full cost before its first request.

## Scope

The result is a best case for allocation: one cohort of 29 hard AIME 2026 questions, all still reasoning at 4K, with values measured on the same questions. Timing is modeled from P1 throughput and runs about 10% fast against the measured no-queue service time, inside the ±25% speed cells. A noisier online predictor would not do better, so this closes the question-level allocation line on this rig. The pressure-only rule "extend whenever nobody waits" was the best adaptive policy, beating fixed 8K by 88 and fixed 4K by 132.

One idea came out of seeing the results: extend freely when the server is idle and consult values only when a queue forms. It is post-hoc and untested. The +11 ceiling suggests little room.

## Reproduce

```sh
python3 -B week8/allocation/build_draws.py      # draws.csv
python3 -B week8/allocation/test_sim.py         # 12 tests
python3 -B week8/allocation/run.py calibrate    # calibration.json, blind to grades
python3 -B week8/allocation/run.py compare      # results/, checks the frozen hashes first
```

[Full results](results/compare.json) · [Per-question accounting](results/questions.csv) · [Sensitivity cells](results/cells.csv) · [Frozen rule](PROTOCOL.md)
