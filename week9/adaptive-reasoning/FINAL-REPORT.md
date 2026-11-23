# LARB research closeout

## Allocation headroom and learnability

Fixed-budget math runs established that reasoning effort changes both accuracy and cost. The 24-question Omni-MATH grid rose from 33.3% at 2K to 60.4% at 8K. Earlier prompt selectors collapsed, and explicit marginal-gain predictors failed to consistently beat cheap controls. Repeated checkpoint sampling, the 56% hindsight token saving on one cohort, and a later Medium–High opportunity audit all describe the same allocation problem.

The final 96-question audit found 10 High-only successes and two Medium-only successes. Learned routing selected High for four of the former and both of the latter. Within-source shuffle would capture 4.56 favorable cases and incur 1.00 unfavorable case on average. Thus the learned mixed-workload GRPO checkpoint finished at 72/96 versus an expected 73.56/96 for within-source shuffle. Hindsight could reach 80/96 by preserving Medium successes and assigning High to all ten observed rescues. That upper bound uses the outcomes and one held-out draw per mode. It does not establish learnability. The learned policy selected High more often on Omni-MATH than GSM8K, but the tested policy did not improve within-source allocation. The central learned-routing hypothesis was not validated for this model, data, and training setup. See the [allocation and workload analysis](WORKLOAD-NOTE.md).

## Serving results

Combined is the proposed policy. Within-source shuffle is the ablation for question-specific assignment. Task-only and load-only isolate the two components.

- In the 12-request pilot, combined and task-only each delivered 7/12 correct on time and 8/12 eventually correct. Combined used 28% fewer output tokens. Shuffled-plus-load also got 7/12 on time, with 7/12 eventual success and 24% fewer tokens than combined. Combined ran in a separate timing-valid allocation on the exact trace.
- Across three eight-slot 24-request bursts, shuffled-plus-load delivered 43/72 correct on time versus 34/72 for combined. At four slots, the two tied at 16/72. Additional shuffles produced 1, 3, and 6 correct-on-time answers on the same four-slot block, showing the sensitivity to a single shuffle assignment.
- On one 48-request sustained trace at eight slots, combined delivered 37 versus 34 correct on time for task-only (+8.8% goodput). Both reached 38 eventual successes, with 104,607 versus 129,017 output tokens (−18.9%). This clears the original +5% goodput and −2-point accuracy rule on point estimates. Combined and shuffle seed 151 tied at 37/48 correct on time. Shuffle used 97,115 output tokens versus 104,607 for combined and had two more eventual successes. At 16 slots, fixed 4K led with 40/48 correct on time. The adaptive arms recorded no pressure-triggered admissions or cuts at that offered rate.
- The one completed coordination block scored 14/24 correct on time for combined, 10/24 for slack-only, and 9/24 for slack plus mode preference. A second block failed at phase setup. The result gives no reason to promote either coordination variant.
- In the offline source-composition shift, the learned policy scored 18, 16, and 21 correct out of 24 on the balanced, Omni-heavy, and GSM-heavy views. Both randomized controls had higher mean correctness and lower mean solver cost on each view. The stronger within-source difficulty shift selected by reference solution without model outcomes. Learned routing had 11 correct and 4,349 mean tokens, compared with expected 11.25 correct and 4,087 tokens for shuffle and 11.52 correct and 3,448 tokens for the frozen source-aware random control. The targeted shift has no live replay. These diagnostics reuse archived outcomes. [Shift archive](results/closeout/evidence.json)

These findings support deadline-goodput evaluation under real queueing and show a useful token reduction from load adaptation in some settings. They leave question-specific learned routing without a consistent advantage over strong randomized controls.

## Final experimental branch · global probabilistic allocation

The development-only rule selected 60% Medium and 40% High. On 96 held-out questions it scored 76.25% expected accuracy at 2,594 solver tokens per request, compared with 76.63% and 2,852 for within-source shuffle, and 75% and 3,161 for learned routing before charging its routing prefill.

PACE job **7324648** tests coin-only and coin-plus-load on the existing eight-slot 24-request burst, using the same draw within each seed pair. Seeds **151** and **411** produced six and seven High assignments, respectively. The engine, adapter, traffic, and scoring limits remain pinned. The administrative drain is longer. Reuse earlier L40S arms only after checking the exact emitted trace and timing-valid status. Across allocations, report the residual hardware and time-order limitation. Compare deadline goodput, eventual accuracy, output tokens, queue waits, latency, and logged and binding cuts.

**Live result.** Job 7324648 completed in 43m 17s on one L40S. All four arms passed the timing checks, with maximum scored client injection of 22.4 ms and engine submission of 187.3 ms. The scored trace was byte-identical to the archived eight-slot controls. Results are on the same 24 questions and 220-second deadline.

| Policy | Correct on time | Eventually correct | Goodput/min | Output tokens | Mean queue, s | p95 latency, s | Pressure admissions | Cuts logged / binding |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Coin 151 | 15 | 21 | 3.75 | 53,471 | 67.6 | 329.8 | 0 | 0 / 0 |
| Coin + load 151 | 15 | 19 | 3.75 | 44,946 | 62.8 | 253.9 | 5 | 1 / 1 |
| Coin 411 | 16 | 19 | 4.00 | 47,811 | 68.2 | 274.3 | 0 | 0 / 0 |
| Coin + load 411 | 15 | 18 | 3.75 | 42,127 | 54.9 | 240.0 | 2 | 4 / 1 |
| Combined | 12 | 20 | 3.00 | 51,197 | 79.6 | 320.3 | 2 | 4 / 3 |
| Within-source shuffle + load | 15 | 18 | 3.75 | 48,990 | 66.9 | 289.5 | 1 | 5 / 3 |
| Load-only | 11 | 20 | 2.75 | 61,012 | 101.9 | 384.6 | 12 | 11 / 4 |
| Task-only | 10 | 19 | 2.50 | 63,375 | 91.2 | 442.2 | 0 | 0 / 0 |
| Fixed 4K | 12 | 20 | 3.00 | 60,188 | 98.6 | 387.5 | — | 0 / 0 |
| Fixed 8K | 12 | 21 | 3.00 | 74,661 | 108.3 | 483.6 | 0 | 0 / 0 |

Across the two seed pairs, adding load adaptation saved 14.0% of output tokens and reduced queue and tail latency on each seed. It changed correct-on-time outcomes from 31 to 30 and eventual correctness from 40 to 37, across 48 replayed requests. Both coin-plus-load seeds matched the archived shuffle's goodput with fewer tokens. These controls ran on separate L40S allocations, and two different random assignments of one trace do not constitute two independent workloads. The realized High shares were 6/24 and 7/24. The result supports a deployable baseline that does not depend on evaluation questions or source labels. It does not establish a general goodput advantage from adding load awareness.

This is the final experimental branch. No training, predictor changes, or further shift runs were launched.

## Agent workloads

Controlled agent fixtures preserved structured tool calls at binding reasoning caps. Customer fidelity blocked trustworthy full-episode evaluation. Whether observable multi-turn states identify useful additional reasoning better than math prompts remains untested.
