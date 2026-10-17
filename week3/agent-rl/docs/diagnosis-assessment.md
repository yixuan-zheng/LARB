# Rollout-to-learner diagnosis

Analysis-only round. No GPU jobs, workload changes, scheduler changes, or training runs were launched. This report reconstructs existing native TIR traces and checks the pinned AReaL implementation. It does not measure a GroupGate benefit.

## Measurements

Matched descriptive window: first eight logged updates, each consuming eight four-member groups. Dynamic sampling has only three updates and is reported separately. Native timings exclude evaluation; dispatcher timings measure active_submit_and_wait, not pure GPU idleness.

| Existing arm | Updates | Dispatcher collection seconds | Sum of native non-evaluation stages | Rollout fraction of stage sum | Mixed groups consumed | Median last-member-end to batch return |
|---|---:|---:|---:|---:|---:|---:|
| Wide async, lookahead2/concurrency16 | 8 | 48.46 | 84.88 | 57.1% | 30 | 13.4ms |
| Capped, lookahead2/concurrency8 | 8 | 130.66 | 166.70 | 78.4% | 34 | 14.5ms |
| Fresh gating | 8 | 235.46 | 259.98 | 90.6% | 29 | 17.2ms |
| Native dynamic sampling | 3 | 121.48 | 133.36 | 91.1% | 24 | 11.2ms |

The dispatcher interval sum agrees with native rollout stage sums within 0.014 seconds in each arm. This supports interpreting the stage as batch acquisition, rather than total background inference time. Stage sums are recorded sequential learner-side scopes, not accelerator utilization measurements or scheduler-recoverable savings. They exclude startup, evaluation, and some unscoped overhead, including the pause preceding timed weight update.

Over the first-collection-to-last-return window, observed completed-generation token rates are 2,245/s wide, 1,507/s capped, and 579/s fresh; consumed mixed-group rates are 0.363/s, 0.208/s, and 0.112/s respectively. These count generation calls ending in the window, including unconsumed work; they are not backend token-throughput counters. Policy evolution and different generated lengths prevent interpreting this as a fixed-workload concurrency sweep. Nevertheless, these observed runs do not show an opposing token-throughput versus mixed-group-delivery trend: wide is better on both descriptive metrics.

## Timeline findings

At the seven post-initial collection starts in wide async, observed ready/unconsumed group counts are 5,1,5,1,3,1,5; unfinished group counts are 11,15,11,15,13,15,11. All observed ready groups appear in the returned batch. Each batch needs eight groups, so each interval starts with insufficient completed groups. We find no observed reservoir of eight ready groups being unnecessarily withheld in this arm.

The median interval from the last member's workflow_end to dispatcher return is 13.4ms; maximum 88.7ms. This is consistent with completion shortage dominating the measured wait rather than a large post-completion handoff delay. workflow_end precedes final serialization, transfer, and acceptance, so it is an observed readiness proxy, not an exact controller enqueue timestamp. Cross-process wall-clock timestamps are on the same node, but not a calibrated distributed clock. Completed groups can be available early and then wait for batch assembly: median group-end-to-return is 3.71s wide, 6.92s capped, 19.75s fresh, 23.73s dynamic. These residence times are not individually recoverable wall-clock losses.

Wide's initial collection is 15.50s; subsequent seven collections total 32.96s. The wait is not just first-batch startup. However, across eight-update windows, mean collection time falls 6.06 -> 2.08 -> 0.96s/update, and native rollout-stage share falls 57.1% -> 44.2% -> 29.8%. Earlier saved measurements show calculator use also drops sharply. This is consistent with a changing workload, not proof of its cause, and means early-stage headroom cannot be extrapolated throughout training.

During first-eight-update collection windows in wide async, 31 generation requests across 16 groups start after mixedness is already observed, producing 9,511 tokens. This combines learner-side waiting with the previous priority-opportunity audit. It still does not establish simultaneous gate queue contention, backend eligibility, criticality to the current batch, or achievable savings. Some such groups can be consumed later or remain unconsumed. Request start is inferred as generation_end.time minus recorded seconds, which includes client wait.

## Closest mechanisms

Pinned AReaL source: areal/infra/staleness_manager.py get_capacity caps new rollout capacity using concurrency and (lookahead + current_version + 1) * consumer_batch_size - (accepted + running). BatchTaskDispatcher.active_submit_and_wait submits pending inputs and drains accepted results until a batch is full. should_accept_fn is invoked after workflow output processing. The learner's rollout timer encloses batch acquisition; inference is paused before timed weight update. Therefore existing admission and group selection are real coordinated controls, not absent functionality.

StaleFlow's design is more directly overlapping than a generic staleness baseline: section4.3 explicitly reserves buffer entries per trajectory group, occupies an entry only after all members complete, and supports group/batch redundancy and filtering. Section5 and AppendixD describe snapshot-based routing, synchronization, and migration. AppendixC reports redundancy-induced length-distribution shift and excludes redundancy from its main comparison for that reason. This is important competing ground, not proof that our conditions are solved. We reviewed paper mechanisms, not its runnable implementation; no absence claim about reward-aware continuation priority is established.
Source: https://arxiv.org/html/2601.12784v2

GAS's published abstract couples curriculum, execution-aware staleness budgets, and task difficulty. We have not inspected its full implementation, so it cannot establish either coverage or absence of our group-level decision.
Source: https://proceedings.mlr.press/v306/zhang26bc.html

## Diagnosis and next intervention

Established: batch acquisition materially blocks the learner in this setup; native wide concurrency reduces it substantially; completed-group handoff delay is small in wide; remaining wait coexists with unfinished groups and some known-mixed continuations. Not established: excessive new starts cause the shortage, reward-aware priority can recover it, or the existing controls leave a general unresolved gap. The proposed throughput-versus-delivery conflict is not observed in these configurations.

Recommendation: target completion during learner batch shortages, rather than throttle starts on an assumed overlaunching problem. One small fixed-policy native comparison on the proven TIR workflow should use native admission, matched FIFO gate, and GroupGate at the same gate capacity, with identical group sizes and no cancellation; apply the same native mixed-group filter across arms. Preserve unfiltered pilot as context, not a mismatched comparator. Preflight must confirm both mixed outcomes and queued admission requests in the live engine before the comparison. Use balanced arm order or repeat FIFO once to detect engine warmup/order effects. Report accepted complete groups per total accelerator-second, completion latency, generated tokens, gate queue contention, and all drained leftovers. Fixed-policy results establish delivery effects only, not learning or policy-age improvements.

Smallest missing instrumentation: controller result enqueue/filter timestamp and queue occupancy; dispatcher request/return; gate enqueue/grant/release; rollout pause/resume/version-publication timestamps. Existing workflow events lack backend runnable-queue state, so do not infer that all 48.46 seconds are recoverable. If the gate changes order without improving useful delivery, diagnose batching and criticality before adding a learner-demand or age policy. No broader scheduler should be built from these traces alone.

## Artifacts and verification

analysis script: work/agent-rl-diagnosis/analyze.py. diagnosis.json contains aggregate stages and distributions; batch-timeline.csv and group-timeline.csv reconstruct first-window observations; wide-training-windows.json separates later wide behavior; priority-wait-overlap.json records retrospective opportunity overlap. The audit asserts eight groups per returned batch and four distinct completed members per group, and checks returned IDs against raw events. Source traces remain under outputs/agent-rl-tools/raw. These are single-run comparisons without training-seed replication. New compute cost: zero GPU-hours.
