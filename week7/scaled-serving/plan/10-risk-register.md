# 10. Risk register

Each row is a way the scaled rig can fail, change what is measured, or waste a GPU allocation. The
mitigation is a gate or a design choice, not a hope. Likelihood and impact are planning judgements.

| # | Risk | Likelihood | Impact | Mitigation / trigger | Fallback |
|---|---|---|---|---|---|
| 1 | Throughput at 32 slots is below the roofline; the main run does not fit 16 h | Medium | High | Gate C measures the curve; N is set from the measured rate | Use the knee (16-24 slots), fewer seeds, or two jobs |
| 2 | KV memory or CUDA-graph memory causes OOM at 32 x 8k | Medium | High | 8k full budget, 12,288 context, 0.85 utilisation; Gate C records KV and preemptions | Reduce to 24 slots, 0.90 utilisation, or 6k full budget |
| 3 | Preemption/recompute makes service times and policy effects uninterpretable | Medium | High | Log preemptions per request and per phase; report them next to the score | Reduce concurrency; treat preemption as a finding, not a nuisance |
| 4 | CUDA graphs change cue positions or token outputs | Low-Medium | High | Gate B compares exact positions and token IDs | Eager main path; graphs as a separate experiment |
| 5 | Row-move bookkeeping loses state at high concurrency | Medium | High | 64-row CPU simulation + Gate A with non-zero rows and swaps | Fix controller; do not run main |
| 6 | Short answer contract changes accuracy | Medium | High | 384-response bridge; only adopt if within 2 points and caps fall | Legacy 2,048 contract; recompute N |
| 7 | Answer cap remains the dominant failure mode | High | Medium | Measure answer-token distribution; short contract gate; cap rate reported | Choose a short-answer pool or GPQA-style letters in an extension |
| 8 | Dataset slope is flat or accuracy is at ceiling/floor | Medium | High | 216-response slope screen: 144 on a disjoint 2023-2024 set plus 72 on a 24-question main-cohort preview; pool-level pass/fail | Change pool (Omni-MATH hard subset or another event family) |
| 9 | Contamination drives the result | Medium | Medium | Exposure tags; fresh subset (AIME 2026, HMMT Nov 2025/Feb 2026) analysed separately | Report fresh-subset result; do not claim a clean test |
| 10 | Pressure threshold never fires or fires constantly | Medium | High | Gate F records pressure fraction in low/sustained/burst; threshold is capacity-relative | Adjust threshold/arrival rate in calibration, then freeze |
| 11 | Pressure cuts are too aggressive; accuracy collapses vs fixed8k | Medium | High | Progress floor/ceiling, cascade, one cut per step; H3 non-inferiority check | Later/smaller/selective cut extension; do not make a serving claim |
| 12 | Deadline saturates (0% or 100% misses) | Medium | High | Calibrate arrival rate to 15-40% reference misses at a declared 180 s SLO | Adjust load, not deadline; 240 s fallback if no load works |
| 13 | Run-order or thermal drift explains the arm difference | Medium | High | Rotated orders; low-load control; A/B/A check; second block if needed | Report order effect; replicate before claiming |
| 14 | Fixed-short (`fixed4k`) wins | Medium | High | Pre-registered as a real competitor; fixed6k calibration | Report the static-budget result; pivot the research claim |
| 15 | The observed effect is 2-4 points, underpowered | High | Medium | Pre-register MDE ~5 points; no tie claim; resolution extension | 500-800-question extension or second block |
| 16 | Engine crash or Slurm timeout mid-run | Medium | Medium | Resumable phase runner; per-phase manifests; outputs outside the repo quota | Rerun only missing phases from the frozen trace |
| 17 | Log volume exceeds quota | Medium | Medium | Stride-8 snapshots, full snapshots only around cuts; 20 GB cap; compression | Reduce snapshot fidelity, keep per-request records |
| 18 | Injection lag > 1 s invalidates a phase | Low | Medium | Client timestamps; 1 s guard; phase marked invalid and repeated | Repeat the phase; never analyse an invalid injection |
| 19 | Prefix caching / warm-up benefits later arms | Low | Medium | Prefix caching off; filler warm-up only; engine drained between phases | Keep off; report prefill separately |
| 20 | Multiple comparisons produce a false headline | Medium | High | Three pre-registered primary comparisons; Holm; secondary descriptive | Report all arms and CIs; no post-hoc promotion |
| 21 | Manual grading corrections bias the result | Low | High | Frozen grader; hash-and-reason review; corrected and uncorrected scores | Report both; no corrections after the primary analysis |
| 22 | Data license or attribution is missed | Low | Medium | Manifest records dataset id, revision, license, attribution; CC BY-NC-SA noted | Do not redistribute raw data outside the terms |
| 23 | The 16 h partition is unavailable or preempted | Medium | Medium | Book early; resumable phases; a second allocation for missing phases | Run the main path over two jobs |
| 24 | The model or engine is silently upgraded | Low | High | Pin model revision, vLLM 0.11.2, torch 2.9.0, transformers 4.57.6; source lock | Re-run the bridge; treat as a new baseline |
| 25 | Filler traffic distorts the quality endpoint | Low | Medium | Filler never scored; fixed 1,024 budget; same mix across arms | Reduce filler share; analyse signal-only |
| 26 | The small cohort cannot answer the 3-point clause | High | Medium | State it up front; report CI; resolution extension | Earn the 3-point claim with 500-800 questions |
| 27 | The result is positive only in one condition | Medium | Medium | Report sustained and burst separately; no pooling without a pre-registered rule | Treat condition-specific effect as the finding |
| 28 | The pressure rule is tuned on the main data | Low | High | Gate F uses disjoint screening items; threshold frozen before main | Discard the run and repeat with a new trace if violated |

## 10.1 The three risks that would stop the main path

1. **Gate A or B fails.** A controller or graph defect makes the measurement meaningless. Stop and
   fix; do not run a larger job on a broken contract.
2. **Gate E fails.** A flat pool cannot test the hypothesis. Change the pool before spending the
   16 h main allocation.
3. **Gate F cannot produce a 15-40% reference miss rate.** The metric is saturated; the experiment
   would produce a decorative tie. Revise the load or the declared SLO before measuring.

## 10.2 The three risks that would change the interpretation, not stop the run

1. **Preemption is frequent.** The system is under KV pressure; report it and treat shorter budgets
   fitting more requests as a finding, not a nuisance.
2. **The effect is condition-specific.** Report it; do not pool it into a headline.
3. **The fresh and exposed subsets disagree.** Report both; contamination or distribution shift is
   a live explanation.

