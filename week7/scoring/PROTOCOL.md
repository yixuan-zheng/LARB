# Week 7 | Cost-matched scoring protocol and decision rule

This protocol sets how any continuation-benefit predictor is scored, how much it may cost, and what evidence earns it a further GPU study. It builds on the [Week 6 research handoff](../../week6/research-handoff/README.md) and the [Week 7 predictor experiments](../README.md). The scripts check every reused input against its published result before computing anything new.

**Decisions requested at the week-end review**

1. **Adopt the scoring rules** in Sections 2–3 for any future predictor test.
2. **Accept the stopping condition** in Section 4. The recommendation is to:
   - keep question-only allocation as the baseline;
   - stop predictor-only GPU studies;
   - move the remaining effort to frozen-budget scheduling in the scaled serving workload, the backup named in the Week 7 plan.

   Reopen the predictor line only if a new candidate passes Gate A, the CPU screen in Section 4, on existing data at near-zero cost.

**Why.** No tested predictor passes. The readers we measured cost about 9 to 640 times what they can afford per checkpoint, and the 27B reader alone takes longer than the 180 s deadline. The only near-free signal, the hidden-state probe, gained 2.2 points on protected questions against a 3.45-point bar, with an interval that includes a loss.

## 1. What is being scored

A predictor sees a request at the 4,096-token reasoning checkpoint and outputs a continuation score. A policy extends the top-scored requests to 8,192 tokens and forces an answer on the rest. The score should estimate the expected gain from continuing, P(wrong→right) − P(right→wrong), not correctness itself.

| Term | Meaning |
|---|---|
| Checkpoint | A request still reasoning at 4,096 tokens. Only these can be extended. |
| Question-only | The control: a score from the question text alone, shared by every seed of a question |
| Half allocation | Extending the top-scored half of checkpoints, the operating point used in Weeks 6 and 7 |
| All-long accuracy | Correct answers when every checkpoint is extended to 8,192 tokens |
| Served-token equivalent | The cost unit: one decode token of the served model, Qwen3-4B |
| Headroom | The most a predictor can cost per checkpoint and still tie question-only at equal accuracy, if its ranking were free |
| Experiment 3 | The Week 7 hidden-state validation: 329 checkpoints from 180 protected questions, our only protected cohort |

Each comparison uses one row per checkpoint: question ID and seed, short and long correctness and cost, the predictor score frozen before outcomes are joined, and for a reader its measured tokens, wall seconds and hardware.

## 2. Scoring rules

1. **The control is question-only.** Every predictor is compared with a question-only score from the same cohort. A reader-based predictor is also compared with the same reader given only the question. That separates "this reader is better" from "seeing the trajectory helps."
2. **Charge the reader on every checkpoint.** A predictor must score every checkpoint before ranking, so its cost is paid on all of them, not only the extended ones. Question-only is charged zero, which favors the baseline.
   - *Tokens:* reader input and output tokens each count as 1 × model scale (reader parameters ÷ served-model parameters). Charging input at full decode cost is a conservative bound until the prefill-to-decode ratio is measured on our GPUs.
   - *Latency:* while the reader runs, the request waits in its slot or decodes tokens it may discard. Either way the cost is at most reader seconds × 66.6 tokens/s, the per-slot decode rate at 32 slots ([scaled-serving gate P1.3](../scaled-serving/reports/P1-REPORT.md)). This stall charge is reported beside the token charge, not folded into the curves.
3. **Report three endpoints.** Tied scores at the cutoff share the remaining slots evenly.

   | Endpoint | Role |
   |---|---|
   | Correct answers at question-only's half-allocation cost (matched realized cost) | **Primary.** More correct answers for the same compute? |
   | Cost to reach question-only's half-allocation accuracy (equal accuracy) | Secondary. Expresses the gain as compute saved, which sets the headroom. |
   | Correct answers at the same extension count | Continuity with Weeks 6 and 7 only. Same count is not same cost. |

4. **Group uncertainty by question.** Resample questions 10,000 times, keeping each question's seeds together and recomputing the half-allocation cutoff each time. Report percentile 95% intervals.
5. **Report misses and harms:** beneficial checkpoints missed, harmful ones selected, and within-question concordance on questions whose seeds differ in benefit. Lift that comes mostly from moving extensions between questions reflects question difficulty, not a trajectory signal.
6. **No tuning after outcomes.** Thresholds, budgets, cohorts and reader prompts are fixed before outcomes are joined. A failed gate is not retried with a new threshold, seed or question set.

## 3. Overhead bounds

| Source | Headroom per checkpoint | Conservative bound |
|---|---|---|
| Week 6 cohort, full-prefix AI readers (best ranking observed) | 1,433 at all-long accuracy; −3 to 1,501 across targets of 21–28 correct | 124 (bootstrap 2.5%) |
| Experiment 3, hidden-state probe | 487 at question-only's half-allocation accuracy | **0**: the interval includes a loss |

On development data, a reader can afford about 124 tokens per checkpoint at the conservative bound, or 1.9 s of stall. At the lowest target, one answer above forcing every answer, it can afford nothing. On protected data, only a near-free predictor qualifies. Measured costs per checkpoint, in served-token equivalents, with multiples taken against the 124-token bound:

| Reader | Tokens | Stall (mean wall time) | Total | Within headroom? |
|---|---|---|---|---|
| Hidden-state probe | ≈ 0 | Unmeasured; needs an engine hook | ≈ 0 plus the hook | Yes, if the hook is near-free |
| Bounded 512-token reader, 4-bit Qwen3-4B | 892 | 204 (3.1 s) | 1,095 | No, about 9× |
| Full-prefix reader, Qwen3.8-27B | 57,892 | 21,438 (322 s) | 79,330 | No, about 640×; its wall time exceeds the 180 s deadline |

## 4. Decision rule

**Gate A: development screen (CPU only, existing data).** A predictor earns a protected-validation proposal only if all of these hold:

1. Its matched-cost lift over question-only, after charging its measured cost, is at least 3.45 points, the threshold Experiment 3 froze.
2. Its measured cost per checkpoint is within the conservative headroom in Section 3.
3. It selects no more harmful checkpoints than question-only.
4. If it claims a trajectory-level signal, its within-question concordance is above 50%.

On the Week 6 cohort, criterion 3 cannot fail, because no checkpoint went from right to wrong. Criterion 4 rests on only four questions whose seeds differ in benefit, so one question moves it by 25 points. Question-only scores 50% by construction, since it ties both seeds.

**Gate B: protected validation (GPU, frozen before outcomes).** The matched-cost lift needs a point estimate of at least 3.45 points and a question-grouped lower 95% bound above zero, with the predictor's cost charged. The study is sized in advance for 80% power at the development effect.
- **If it fails:** stop that predictor and record the result.
- **If it passes:** it moves to the serving workload. There, the decision metric becomes correct answers delivered before their deadlines.

**Stopping condition.** If no candidate passes Gate A, keep question-only allocation as the baseline and run no further predictor-only GPU studies.

## 5. Current candidates

Costs are in Section 3.

| Predictor | Key result | Verdict |
|---|---|---|
| Week 6 full-prefix AI readers | +4 per 57 at matched cost if reading were free (interval 0 to +9) | Fails Gate A (2): reading cost never measured |
| Bounded 512-token reader | 22/57 at 28 extensions even with free reading, below both controls (24 archived, 25 for the same reader); 25% concordance (1 of 4) | Fails Gate A (1, 2, 4); stopped in Week 7 |
| Recoverable-step reader | 25/60 versus 26/60 at the charged ceiling | Fails Gate A (1); stopped in Week 7 |
| Qwen3.8-27B full-prefix reader | At equal extensions, +6 over its own question-only control on Week 6 (+3 over archived) and −1 on Week 7. Free headroom at most 2,309 tokens per checkpoint over its own control, 580 over archived | Fails Gate A (1, 2) |
| Hidden-state probe | +2.2 points at matched cost on protected data (interval −0.3 to +5.0); 46% within-question concordance | Failed Gate B: below 3.45, lower bound below zero |

Three later follow-ups, a nonlinear readout, temporal checkpoint features and a repair-evidence screen, also failed to show a within-question signal ([follow-up results](../follow-up/RESULTS.md)).

**No candidate passes.**

The hidden-state probe is the only one worth keeping on record. By the Experiment 3 planning proxy, which assumes similar clustering and eligibility, a decisive test of its 2.24-point lift at 80% power needs about **460 protected questions** and **220 base L40S-hours**, 2.3 times the Experiment 3 budget. A gain this small is unlikely to justify that before the serving workload shows it matters.

## Reproduce

Run from the repository root. The scripts use only the standard library, except `protected.py`, which needs NumPy.

```sh
python3 -B week7/scoring/build_sheet.py   # per-checkpoint sheet; checks Week 6 and Week 7 published allocations
python3 -B week7/scoring/frontier.py      # question-only vs Week 6 full-prefix curves; misses, harms and concordance
python3 -B week7/scoring/overhead.py      # measured reader costs, latency and headroom, against both controls
python3 -B week7/scoring/bootstrap.py     # question-grouped intervals; reproduces Week 6 intervals exactly
python3 -B week7/scoring/protected.py     # Experiment 3 cost-matched view; reproduces its published interval exactly
```

## Limitations

- **Cost units are approximate.** Prefill is charged at decode cost and model scale is a parameter-count proxy. Both favor the baseline, and neither is measured on our hardware.
- **Week 6 numbers are exploratory.** All 30 Week 6 questions have been explored, so they are development evidence only.
- **The Experiment 3 matched-cost and equal-accuracy analyses were not pre-registered.** They describe that result but do not change its decision.
- **Latency, synchronization and memory are only partly charged.** Wall times were measured off the serving GPU (bounded reader warm on Apple Metal, 27B reader on one A100 at concurrency 8), so they show order of magnitude only. A co-resident bf16 27B reader would need about 54 GB for weights, most of the memory the KV cache uses, and the probe's engine hook has an unmeasured synchronization cost. All of these only add to the charges.
- **Token and call-time costs are not serving outcomes.** Queueing, batching and deadline effects are left to the serving workload.
