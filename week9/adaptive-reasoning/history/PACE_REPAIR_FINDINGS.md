# PACE repair-round findings · November 18, 2026

**Both jobs completed successfully.** The Omni-MATH grid confirms budget sensitivity on this cohort, while the tested selector assigns every question 2K. The local τ²-bench agent passed the binding 2,048-token tool-call test. Customer fidelity is still the main blocker, with different errors at 3B and 7B.

| Job | Hardware | Allocated elapsed time | GPU-hours |
|---|---|---:|---:|
| 7159530 · Omni-MATH | 1 L40S | 2h 14m 18s | 2.24 |
| 7159581 · Local τ²-bench | 1 L40S + 1 A40 | 11m 01s each | 0.37 |
| **Total** | | | **2.61** |

## Omni-MATH

The Python 3.10 timeout regression passed on PACE. The fixed grid completed all **192 solves** at four slots, with 24 questions and two seeds per budget. The solver averaged 93 input tokens at every cap. The harness counts answer-cap terminations as failures.

| Reasoning cap | Correct / 48 | Accuracy | Mean reasoning tokens | Mean total output tokens | Answer caps |
|---:|---:|---:|---:|---:|---:|
| 2,048 | 16 | 33.3% | 2,048 | 3,415 | 11 |
| 4,096 | 23 | 47.9% | 4,069 | 5,171 | 2 |
| 6,096 | 26 | 54.2% | 5,937 | 7,052 | 4 |
| 8,192 | 29 | 60.4% | 7,632 | 8,767 | 3 |

The 2K-to-8K gain was **27.1 percentage points** at about **2.57×** the output tokens. Both seeds showed higher accuracy as the cap rose. At adjacent caps there were also wrong-way flips, including three 6K-correct results that failed at 8K. The curve applies to this cohort and answer contract.

The constrained decoder returned **24/24 valid labels**, all **2K**. Replaying these choices yielded **16/48 correct**, identical to fixed 2K and the histogram-matched shuffle, which collapses to the same assignment when every choice is 2K. Selection added **155 input tokens, 3 output tokens, and 54 ms mean idle latency** per request. The loaded call timed out at **30 s** and fell back to 4K. On 17 question-seed pairs the selector chose 2K and failed while another cap succeeded. The experiment ran the fixed caps live and evaluated adaptive choices by replay.

**Recommendation:** Use the fixed grid as evidence of budget sensitivity. Retire this selector from the pilot design unless a revised question-only rule demonstrates nonconstant assignments and an advantage over the fixed and shuffled controls after cost. Hold the combined-policy serving pilot.

## Local τ²-bench

Both simulator checkpoints returned **12/12 responses** across nodes on identical English airline/retail fixtures. The follow-up turns included scripted preceding dialogue. The median client-observed latency was **0.63 s for 3B** and **0.91 s for 7B**, with a first-call outlier of 10.35 s for 3B. Peak sampled memory was **41,435 MiB** on L40S and **29,901 MiB** on A40, including engine reservations.

| Fixture | 3B | 7B |
|---|---|---|
| Airline 0 · cancellation only with refund | Accepted the no-refund proposal and drifted toward the agent role. | Rejected the proposal and raised the prior insurance guidance. |
| Airline 2 · delayed reservation | Refused the offered change but did not explicitly say it could not recall the booking number when asked. | Preserved that the booking was the last one made and that the number was unknown. It avoided accepting the change but did not explicitly acknowledge the passenger-count correction. |
| Retail 1 · thermostat-only fallback | Preserved the thermostat-only fallback when the exact keyboard was unavailable. | Preserved the same fallback. |
| Retail 2 · T-shirt count and three returns | Preserved the three returns and asked whether they had been initiated. | Recast the returns as a request for item details or availability. |

These are manual fixture observations. The sample does not establish an overall reliability ranking.

**Agent interface:** Controller telemetry recorded forced closure at exactly **2,048 reasoning tokens**. The request returned a parsed lookup call with the expected order ID and a call ID, used **2,078 completion tokens** in **29.53 s**, and correctly reported the delivery status after receiving the mock tool result. The fixture suppressed early close, tool-start, and EOS tokens to exercise the boundary. The 512-token forced-close check also passed. This validates the tool interface at a binding cap. Full airline/retail database writes and episode grading remain outside the fixture test.

**Recommendation:** Keep the two-endpoint architecture and the cap implementation. Do one focused customer-fidelity check on the contradictory airline and retail cases before running the 12 episodes. The 7B checkpoint is worth retaining as a candidate, but the retail regression rules out a blanket switch based on these fixtures.

PACE evidence is in `~/scratch/larb-math-repair-20261118/summary.json` and `~/scratch/larb-tau-repair-20261118/results-7159581/`. No combined-policy serving pilot, full agent episodes, or paid calls ran.
