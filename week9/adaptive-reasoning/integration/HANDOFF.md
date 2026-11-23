# Scaling handoff

## Reviewed versions and compatibility

Remote heads were refreshed for the Week 9 closeout on November 25, 2026. The four reviewed branches remain at the versions below. The Week 9 base is `origin/main` at `4f265c9c`.

| Branch / commit | Reviewed material and status |
|---|---|
| [scaled-serving · 9fd5c5a6](https://github.com/yixuan-zheng/LARB/tree/9fd5c5a6645a402ad343fedaa43f854a4e851e1d/week8/scaled-serving) | Week 8 README, server entry, qualification and pool results, P2 draft and launcher. Shared Week 7 vLLM V1 Qwen3 rig on one H100 80 GB with 32 slots, eager mode and legacy answer contract. P2 draft remains withheld. AIME 2025–2026 candidate showed a replicated +18.8-point exploratory 4K→8K slope on 48 questions per seed, while the formal preview was grader-inconclusive. |
| [allocation · 2d0be72b](https://github.com/yixuan-zheng/LARB/tree/2d0be72b62a227df82a3bfbea1044d730c5f1258/week8/allocation) | Frozen protocol and results for the 32-slot CPU AIME checkpoint simulator. 1,229 burst arrivals at 540/h, 240 s deadline. Question-aware 516 good versus pressure-only constant 545, paired difference −29 [−52, −2]. The measured-value policy beat its equal-extension shuffle but lost to a stronger pressure control. This is simulated checkpoint continuation evidence. |
| [mixed-serving · 96e8f109](https://github.com/yixuan-zheng/LARB/tree/96e8f1097d2f0be6a513eede6cda04330824da71/week2/mixed-serving) | Historical Gemma 3n width-switching executor. Shares trace and SLO analysis concepts. The Qwen adapter, tokenizer, and worker hooks are incompatible with that model and executor. |
| [scoring · c5668c08](https://github.com/yixuan-zheng/LARB/tree/c5668c08040a0ce40a7e17f4e3ae756e8f6a57d5/week7/scoring) | Cost-matched analysis protocol. PR #13 merged. PR #12 covers the earlier shared scaling rig. GitHub issue list returned no entries at review. |

| Integration item | Published evidence | Ask the scaling team |
|---|---|---|
| Active deployment | The Week 8 wrapper loads its question pool and launches the inherited Week 7 server. The repository confirms the intended one-H100 80 GB, eager, 32-slot profile. | Active checkout SHA and any overlays, exact GPU and slots, vLLM environment, model/tokenizer hash, and latest PACE job and manifest. |
| AIME and grading | The AIME 2025–2026 exploratory slope is encouraging. Formal qualification remains grader-inconclusive in the accessible evidence. The draft selects the legacy answer contract. Our reference has boxed integer scoring and a separate answer allowance. | Sealed question IDs and source lock, grader version and adjudicated edge cases, accepted formatting, and evidence the actual deployment passed qualification. |
| Pressure and P2 | The published P2 config is withheld, has no frozen arrival rate, and is an Omni-MATH draft with 216 signal items, four seeds, 30% filler, 240 s deadline, threshold eight and two-step persistence. The AIME simulator at 540/h is a separate CPU study. | Approved P2 freeze, live traffic and validity logs, verified pressure, matched trace IDs, deadline/drain and allocation limits. |
| LoRA and reasoning enforcement | The inherited rig exposes per-request `extra_args`, a worker logit processor and live budget updates. The accessible team wrapper does not establish same-adapter support, mode-prefix parity or effective cuts on the active deployment. | Confirm engine LoRA flags and request plumbing, exact prefix and worker contract, a binding live cut, and intervention logs reconciled with request records. |

## What to integrate

1. Obtain the verified step-24 adapter and pinned base snapshot using [artifact instructions](ARTIFACTS.md). Install the pinned vLLM environment and confirm LoRA loading on the team's engine.
2. Read [policy definitions](POLICIES.md). Add the stable coin or cached mode input at admission. Use per-request mode-aware prompt tokens. Keep mode choice separate from the ceiling. Map 4K to the High prefix, preserve the final-answer allowance, and propagate policy plus ceiling into worker state.
3. The inherited server's signal defaults select caps by arm. Register the new arm names in phase validation and make trace/request records carry original request IDs and assignments. Enable LoRA in engine args and pass the same adapter in every scored arm. The team loader needs mode routes, shuffle maps for the ablation, and source labels only for that ablation. For new questions, compute cached routes from the pinned step-24 checkpoint via the [root-logit extractor](../serving/replication/cache_margins.py) or a parity-verified equivalent.
4. Reconcile cut logs before scoring. Verify natural, binding, already-closed and absent-worker-evidence cases, plus median and p95 queue/service timing. Reject transport timing violations using preregistered thresholds. Test the phase endpoint and isolation of server ports before replay. Verify that late completions still count toward eventual accuracy.
5. Recalibrate pressure on the team's AIME workload and deadline. The 16-slot mixed run at unchanged offered load produced zero adaptive interventions. Capacity scaling requires a rate that actually creates backlog and opportunities for both admission reductions and live cuts.

## Qualify before scoring

- Load the pinned base and step-24 LoRA on every arm. Compare all three prefixes and token IDs, including a High request capped at 4,096. Confirm natural closure, forced closure, separate final-answer allowance and grading on known answers.
- Stress the actual GPU, slots, workload and deadline. In a quiet fixture, verify no pressure actions. In a pressured fixture, verify waiting work, a pressure admission and a binding in-flight cut, with worker/HTTP telemetry reconciliation. The previously tested 16-slot cell had no controller interventions at its offered rate.
- Keep scheduled arrivals, generation seeds, deadlines and arm definitions matched. Use the client/engine timing gate, preserve eventual completions during drain, and freeze traffic before scoring. Score correct-on-time goodput per offered minute, eventual accuracy, realized tokens, queue/tail latency, and logged and binding interventions. Compare paired blocks, with random assignments nested within workload blocks.

## Priority before Friday, November 27

| Priority | Arms on each matched block | Conclusions supported |
|---|---|---|
| Primary, if compute permits | Fixed 4K, fixed 8K, combined, within-source shuffle + load, probabilistic-only, probabilistic + load | Learned placement versus heterogeneous budgets, practical probabilistic policy versus conventional baselines, and incremental load effect on the probabilistic assignment. |
| Full component ablation | Add task-only and load-only | With the primary arms, isolates load intervention for the learned router and learned routing relative to the same load controller. |
| Reduced, in order | 1. Fixed 4K, combined, within-source shuffle + load. 2. Add probabilistic + load, then probabilistic-only. 3. Add fixed 8K, then task-only and load-only. | The first three preserve the core learned-versus-shuffle comparison and a conventional anchor. The next pair tests deployment and its load effect. The reduced matrix cannot locate both fixed endpoints or interpret every component independently. |

Start with one qualified pressured block. Prespecify assignment seeds and, as capacity permits, replicate on independent held-out blocks before widening concurrency. Retain a quiet sanity cell. For qualified AIME with enough variation in the router's actions, permute within the single AIME source on a frozen roster and report the mode mix and seed sensitivity. If actions collapse or AIME remains unqualified, report that the core comparison is not informative in that cell. Use a separately qualified held-out mixed workload to answer it, and label AIME-only fixed or probabilistic runs separately. Apply the frozen 60/40 policy as-is. Any alternative calibration requires disjoint development data and a separately labeled configuration.

Apply the original +5% goodput and −2 percentage-point accuracy thresholds as point-estimate criteria and report uncertainty over independent blocks. Two random draws of the same workload do not give two independent blocks. The archived eight-slot results are a reference for parity, with a distinct deadline and workload from the team draft.

## Reproduction and transfer

Follow the [reference replay and CPU instructions](REPRODUCE.md), [artifact staging instructions](ARTIFACTS.md) and the [compact evidence](../results/closeout/evidence.json) for job 7324648. The team runtime and packaged GPU launch still need live parity checks on the actual deployment. The code and results are ready for those checks. Integration does not require more training.
