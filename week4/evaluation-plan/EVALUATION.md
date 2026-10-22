# 5A: validation of the unchanged admission/live candidate

Prepared 2026-10-22, before any reserved generation. [plan.json](plan.json) is the machine-readable specification. The question is whether the current live controller improves correct-by-deadline completion beyond admission-only on new questions and more than one traffic condition. This evaluation does not establish novelty.

## Questions and exposure

The [audit](exposure.json) covers tracked Week 1–4 artifacts and preflight files. Stage 3 contains six configurations covering indices 0–99; later LARB runs reuse subsets. Earlier sequential/probe JSONL records are included. No additional MATH-500 references were found in the tracked non-LARB week artifacts. The two setup failures produced zero requests.

Rows 100–499 at dataset revision `6e4ed1a2a79af7d8630a6b768ec859cb5af4d3be` are provisionally eligible. This conclusion cannot exclude untracked or external experiments, collaboration elsewhere, or training-data contamination. Before generation, the run owner can reconcile any additional exposure with the saved list. A changed exposure list produces a revised selection and plan before outcomes, rather than silently replacing individual questions.

The 24 smallest SHA-256 digests of `week4-5A-v1:INDEX` over eligible indices select the cohort without inspecting content or performance. The exact rank order and two 12-question shards are saved. No difficulty filtering, trial generation, or selection by length/answer occurs here. The other 376 provisional questions remain separate for later work. Once any selected question is generated, it counts as exposed even if its job fails.

The runtime input step will fetch pinned `test.jsonl`, verify 500 rows and agreement of its first 100 records/unique IDs with the saved development input, and write the file hash plus selected row/unique-ID hashes. Those fresh input hashes are pending, rather than invented in this plan. The controller receives the prompt and serving metadata; references and solutions remain with the offline scorer. Repeated identical problems/unique IDs across partitions would require resolving the split before launch.

## Candidate and paired execution

[candidate-lock.json](candidate-lock.json) pins existing policy, adapter, service, imports, and grading code. Model revision, vLLM 0.11.2, BF16, two active slots, stock scheduling, eager execution, disabled prefix caching, caps, transition cue, and sampling match the controlled development experiment. The preferred hardware is the previously validated H100 80GB; another compatible device needs a fresh mechanical gate and a separately identified complete matched campaign.

Only **admission and live** run in this bounded validation: both start with the same admission rule. The earlier full/arrival development results remain context, not matched held-out baselines. A broader prior-method comparison has its own 6B/6C plan and budget; it will not be appended after reading these results.

Two shards × three traffic conditions give six jobs. Each job runs two blocks with both policies: admission/live, then live/admission. Block 1 rotates question positions by six so that the same first two problems do not always anchor the burst. Seeds remain `6222 + pinned dataset index`; matching seeds does not ensure matching sampled outputs. Each job uses one engine and one fixed numeric trace for all four phases, with phase drain/cache state checked between phases. No reference answers influence control.

## Calibration and traffic

Each job first runs exposed development indices 0 and 2 concurrently in full mode. These 12 calibration requests across the six jobs are excluded from scores. On the client's monotonic clock, let `S=max(30, larger calibration latency)` and `B=0.25*smaller calibration latency`. Calibration includes final-answer generation. Before any reserved generation, the job saves calibration, numeric arrivals/deadlines, source/input hashes, orders, and horizon.

| Condition | Open-loop scheduled offsets for positions i=0..11 | Relative deadline |
| --- | --- | --- |
| Low load | `2*S*i` | `2*S` |
| Late burst | First two at 0; remaining ten at `B + 0.05*(i-2)` | `2*S` |
| Sustained pressure | `0.3*S*i` | `2*S` |

These are intended traffic conditions, not guarantees about queue occupancy on unseen questions. Measured overlap, waiting time, and live cutoffs will establish the actual load. If the late burst misses ongoing reasoning or sustained arrivals produce little queueing, that is reported; the trace is not retuned on reserved outcomes. A low-load run can still queue behind a long outlier.

Late work drains under common caps. Each condition/job's fixed horizon is `H=max(offset+deadline)`. Goodput is successful answers divided by `2*H` across its two blocks. Shards may have different calibrations, so their rates remain separately visible rather than being divided by an unrelated pooled horizon.

## Outcomes, uncertainty, and decision

There are **288 measured outcomes**: 24 questions × three conditions × two blocks × two policies. Each condition/policy has 48 outcomes but only 24 unique questions.

Primary success requires a correct final answer, normal completion, and client terminal receipt by the deadline, timed from scheduled arrival on that same clock. Caps, errors, cancellations, missing finals, and incomplete answers fail. Eventual normally completed correctness is reported separately. The scorer uses the existing final-answer extraction and pinned Math-Verify 0.9.0 environment; parser issues receive documented, policy-symmetric review without replacing original scores.

The primary contrast is the equal-weight mean live-minus-admission success-fraction difference across the two pressure conditions. Each condition, shard, and block is also reported. Secondary measures are eventual correctness, latency including unsuccessful outcomes, queue time, thinking/cue/answer tokens, binding cutoffs, policy overhead, and allocation time. Tiny-sample P95 is descriptive. All failures remain in the denominators.

The predefined continuation screen is: positive pooled pressure difference; neither pressure condition negative; overall eventual-correctness difference at least -3 percentage points; no condition/block with more than one net eventual-correctness loss out of 24; and no low-load block with more than one net deadline-success loss out of 24. Binding post-progress cutoffs are needed in both pressure conditions to support an intervention interpretation. These observed thresholds are decision aids, not guarantees or noninferiority confidence bounds. A mixed/negative result remains a useful result.

Analysis will show paired gains/losses, per-question mean differences across repeated exposures, shard/block ranges, and a paired question-cluster bootstrap sensitivity interval (10,000 resamples, seed 622205). All repeats of a question move together in that descriptive bootstrap. Queue coupling and only two independent question shards limit inference: this interval does not capture general traffic/runtime uncertainty or establish population significance. No sample-size expansion, seed search, or tuning follows a disappointing score under this plan.

## Resources and readiness

Each of six jobs has a 240-minute allocation, 230-minute driver ceiling, 25-minute startup allowance, and 45-minute phase ceiling. Maximum base allocation is 24 GPU-hours; one specifically diagnosed infrastructure replacement may add at most four hours, giving 28 total. These are ceilings, not predicted usage. After calibration and before reserved generation, a fit check compares remaining allocation with four times `(trace span + 8*S)` plus ten minutes. If that estimate cannot fit, the job stops with its calibration evidence and resource settings can be revised before generation. Startup and shared-storage delays have explicit margin.

A failed scientific outcome does not trigger a rerun. An infrastructure replacement repeats a complete matched four-phase job, retains the original attempt, and uses the same frozen cohort/trace rule. Partial campaigns are reported as partial. A hardware/settings change requires a new matched campaign, not pooling unlike runs.

5A's selection, estimands, traces, decision rules, and resource ceiling are specified. **5B still needs** pinned full-dataset input hashes, the local exposure reconciliation, a runner supporting these shards/rules and immutable plan hashes, and a CPU replay/instrumentation check on exposed examples. No new GPU job was submitted during planning. Numerical calibration and runtime manifests are naturally finalized at execution, before reserved measurement.
