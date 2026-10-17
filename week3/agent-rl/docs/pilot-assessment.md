# Native asynchronous tool-agent RL: final assessment

14 October2026. **There is a substantial scheduling/learning interaction worth investigating, but this run does not establish positive agent-learning progress or a new scheduler that is needed.** The strongest lead is coordinating rollout completion, useful group acquisition, and policy freshness as the policy changes its execution behavior. Existing native controls are effective competitors, not missing functionality.

## What actually ran

AReaL commit`ba237a1b21703417541c2f107adb923d8ca1f504`, upstream TIR agent and math verifier, Qwen2.5-1.5B-Instruct, native FSDP learner and vLLM engine. TwoH200 GPUs,4CPUcores total,96GiB host memory. The learner and generator use separate GPUs. Both native decoupled loss and recomputed log probabilities are enabled; ratio-rejection upper bound5, learning rate6e-6, group size4. No new scheduler, reward function, or RL algorithm was implemented.

Training uses512 seeded GSM8K questions. Evaluation uses32 disjoint held-out prompts with four candidates each. The calculator executes real expressions and returns real results; no injected delays. Python is disabled because the upstream executor explicitly runs unsandboxed code. The upstream TIR prompt alone produced only2 tool-using trajectories among485 completed episodes in an eight-update qualification probe. We therefore added the same explicit-calculator instruction to all final training/evaluation prompts. Exact transformed prompts and references are saved. vLLM's existing stop-string retention option is enabled to support delimiter-based TIR. External wrappers observe events; they do not replace native admission or learning.

**49 optimizer updates were logged in the final investigation, plus8 in the qualification probe.** Final arms: async24 completed; fresh14 logged before intentional interruption, with a complete evaluation at8; capped8 completed; dynamic sampling3 before its bounded allocation ended. Of the49 final updates,45 have positive logged gradient norms. All three scheduling comparisons below use their fully evaluated eight-update checkpoint. Later unevaluated fresh updates are charged to total allocated cost, not claimed as measured learning. Dynamic sampling has no post-training held-out score and is not ranked for learning efficiency.

## Matched eight-update evidence

Elapsed time runs from the first native training collection through completion of the eight-update evaluation. It includes validation and concurrent rollout work, excludes initial model loading and baseline evaluation, and uses the same128 evaluation episodes per checkpoint.

| Native configuration | Time through checkpoint8 | Two-GPU cost | Answer success before → after | Calculator use after |
| --- | ---: | ---: | ---: | ---: |
| Lookahead2, concurrency16 |96.2s|0.0534GPUh|60.9% →60.2%|10.2%|
| Lookahead2, concurrency8 |237.8s|0.1321GPUh|63.3% →50.0%|3.9%|
| Fresh gating, concurrency16 configured |268.3s|0.1491GPUh|60.9% →32.0%|43.0%|

The best-tested native option is **lookahead2/concurrency16**:2.79× less elapsed cost than fresh gating at checkpoint8, with substantially less accuracy degradation. The cap8 control has the same effective maximum training concurrency as fresh gating and remains faster, but its learning behavior differs from the wider async setting. These costs include final evaluation, whose generated workload also differs across learned policies; they are not identical-token microbenchmarks.

Prompt-cluster bootstrap95% intervals for the accuracy changes are async[-11.7,+10.2]percentage points, cap8[-23.4,-3.1], fresh[-39.8,-18.0]. The difference in changes versus fresh is +28.1points[+14.1,+42.2] for async and +15.6points[+2.3,+29.7] for cap8. These are conditional on this single training run per configuration and these32 prompts. They do not cover training-seed variation. Initial checkpoint scores differ slightly despite nominally identical seed/model; asynchronous generation is not bitwise deterministic.

The longer async curve is60.9% →60.2% →63.3% →61.7% at0/8/16/24 updates. **Positive learning perGPUhour is not demonstrated.** Async principally preserves accuracy relative to the other settings here. Changing learning rate, KL regularization, length budget, or other ordinary trainer controls could repair degradation; this investigation did not establish otherwise.

## What explains the remaining opportunity

1. **The policy changes the workload.** Async held-out calculator use falls from40.6% initially to10.2% at8 updates and6.3% at24. Median evaluation episode time falls from11.2s to about3.3s. Correct-with-tool trajectories fall from22.7% to3.9% by24. The native reward only scores the final answer, so avoiding an unnecessary calculator on GSM8K is permitted by the objective. This is not evidence that scheduling improves genuinely tool-dependent agent ability. It also means improvements in raw tokens/second or updates/hour cannot be assumed to measure useful agent learning.

2. **Completed group utility is uneven.** In async24, only68/192 consumed groups have mixed rewards;69.4% of generated training tokens belong to uniform-reward groups. Those groups provide no within-group reward contrast. This is a measure of potential low informativeness, **not a claim that69% of compute can be safely removed**: batch normalization, optimizer state, and other effects matter, and identifying a uniform group generally requires completing its candidates.

3. **Existing dynamic sampling fixes selection after acquisition.** We used AReaL's documented filter`0 < rewards.mean() < 1`, unchanged. Its three logged updates consume24 mixed-reward groups. It also completes37 uniform-reward groups that never enter training, representing161,153 generated tokens. Ten additional completed mixed groups are unconsumed at termination. The run does not prove dynamic sampling is inferior: its8-update target was not reached, there is no post-training evaluation, and startup shared the12-minute follow-up allocation with the capped control. It establishes that filtering useful batches does not itself avoid generating rejected evidence.

4. **Long completions and freshness remain coupled.** Async consumed episode durations range0.47–45.15s, p99 about33.8s. Maximum observed retained-token age is7 updates despite configured head lookahead2; cap8 reduces it to2, fresh to0. The native knob limits admission/head capacity, not a strict whole-trajectory age. Token-ratio rejection peaks below0.063% across tested arms. This is not a newly discovered missing staleness mechanism or a contract violation.

5. **Unfinished work is measurable and usually modest in the completed async run.** Async ends with30 completed unconsumed episodes/8,870 generated tokens, plus34 unfinished episodes containing325 recorded completed-segment tokens. Cap8 ends with12 completed unconsumed episodes and20 unfinished episodes containing17,526 recorded completed-segment tokens. Tokens still inside an unfinished generation request are unknown; all GPU walltime is charged. Dynamic filtering's rejected groups must not be confused with shutdown leftovers.

6. **The selection evidence is limited.** At checkpoint8, wide async shares59/64 source groups with fresh, while cap8 shares64/64. Completed groups preserve four-candidate grouping. This shows completion-order selection at a finite horizon, not a demonstrated permanent exclusion of difficult tasks or a causal explanation for the accuracy difference.

The calculator itself is cheap: typical observed execution about0.3ms, maxima below4ms. The heterogeneity is dominated by model generation, repeated segments, and long/capped reasoning, not slow external tools. Thirty-one of768 accepted async episodes and37 of256 cap8 episodes reach the3000-token sequence limit. Ordinary length-budget tuning remains a serious competing explanation/solution. GPU activity is modest on theseH200s; eager mode and a small model with limited CPU/concurrency are used. These measurements are not claims of peak engine efficiency or an irreducible utilization gap.

## Strongest research opportunity and recommendation

**Pursue learning-aware coordination of heterogeneous agent rollout groups:** how to allocate generation, tool service, and learner capacity so that sufficiently fresh, informative, representative groups arrive at a useful rate as the policy changes its execution topology. The problem is broader than choosing a fixed lookahead and does not require a new RL objective.

A plausible MLSys contribution would be a validated cost/coverage model and coordination mechanism that improves held-out task learning per accelerator-hour over **tuned AReaL lookahead/concurrency plus native dynamic sampling**, with explicit accounting for rejected evidence, unfinished continuations, policy age, and group coverage. A new abstraction or empirical explanation of the tradeoff could be valuable even before a new architecture.

**Continue this direction for one focused next validation; do not build a scheduler yet.** First establish stable learning with ordinary native training controls on a task whose success actually requires tool/state interaction. AReaL's existing tau2 airline example is a concrete candidate; its small-model recipe exists, but it requires a fixed user-simulator service whose cost must be included, and was not installed/run here. Keep the working async16 setting as the strong scheduling baseline and native dynamic filtering as a required comparator. Test whether informative-group acquisition and coverage still limit learning after normal length-budget and optimizer tuning. If those controls resolve the tradeoff, use them and stop the new-mechanism project rather than claiming a gap.

The present ground is concrete: real native scheduling choices change walltime, policy behavior, and quality markedly; the strong native async setting works well relative to the alternatives; generating useful reward contrast costs substantial real work. The unresolved research claim is whether coordination can improve **positive task learning**, not merely preserve a brittle math policy or increase throughput.

## Resource accounting, blockers, and artifacts

All jobs have ended; no experiment remains queued. Total physical accelerator allocation is**1.5017GPUhours:0.3967H100 +1.1050H200**. This includes dependency/import failure, qualification probe, cold shared-filesystem startup, evaluations, extra fresh updates after checkpoint8, cancellations, and the dynamic-control time limit. These are physical hours, not hardware-equivalent FLOPs or dollar costs.

One startup failed on a missing`soundfile` import in Qwen-Agent and was repaired. Occupied L40S/H100 devices and CPU scarcity led to the final commonH200 allocation with twoCPUcores per role. Slurm rejected increasing the active allocation's wall limit, so controls were bounded at the shared evaluation checkpoint rather than requesting an extension. Fresh interruption produced the expected FAILED allocation status; dynamic sampling reached the follow-up TIMEOUT. Neither is hidden as a successful24/8-update run.

Results and scripts: `results.json`, `comparison.csv`, `quality-comparisons.json`, `checks.json`, `comparison.png`, `raw/*/profiles/*.jsonl`, exact dataset/model/environment provenance, `important-results.tar.gz` containing native logs/traces, and `reproduction/`. Model weights remain on PACE with their pinned public provenance; trained final checkpoints were not retained. Reproduction requires rerunning the inexpensive updates.
