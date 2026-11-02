# Portable queue-pressure protocol

## Status and scope

This is an essential portable copy of the prepared serving experiment. It has not run on a GPU. A different,previously frozen operational bundle is already queued for synthetic mechanics; see ../STATUS.json. Do not patch that bundle,replace its hash,or submit a duplicate job from this handoff. Monitoring is off at the user's request. Check operational status manually using the private job record before proposing any new allocation.

This package never calls a submission command. Stages require separate review; calibration does not automatically launch measurement. The job wrapper is an execution script,not a scheduler submission tool. Populate operational paths outside the repository; env.example contains neutral placeholders.

## Fixed settings

Qwen/Qwen3-4B revision1cfa9a7208912126459214e8b04321603b3df60c; MathArena/aime_2025 revisionc94da77eb22bbd6439e62a323bec18493a421302. vLLM0.11.2,torch2.9.0,Transformers4.57.6;bf16,eager,prefixcacheoff,context24576,max_num_seqs2,max_num_batched_tokens2048,GPU memory utilization setting.8,temp.6,top-p.95,top-k20. Preserve cue text in spec.json and legacy2048-token answer-cap semantics,including trailing cue tokens. These are thinking allowances,not total generation limits.

## Policies

- fixed4k:4096 at admission;no live changes.
- fixed8k:8192 at admission;no live changes.
- live:8192 under observed slack;4096 if at least one same-phase scheduler waiter is observed at arrival. When a waiter appears,reduce each eligible open request's budget toward4096 once.

The trigger is a predeclared queue-nonempty rule,not a calibrated GPU-capacity estimate. Below4096tokens,the request may continue to4096 or close naturally earlier. Above4096,the cue starts at the current token count on the next controller step,with no rewind or retry. Naturally closed thinking and already-cued/answering requests are excluded. A cut is irreversible for that request;subsequent admissions can receive8192 after pressure clears. Batch-row state follows the request. The FIFO estimator is not consumed by this rule.

Arrival-only adaptation is implemented as a diagnostic but excluded from the initial72-request pilot. Add it explicitly before attributing any observed benefit specifically to in-flight intervention.

## Gates and resources

1. CPU:source/AST/shell checks plus15policy/workload/analysis tests. Independent FIFO copy has14tests.
2. Synthetic mechanics:oneH100,8CPUs,64GRAM,1h outer cap/50m inner timeout,two outputs. mechanics_adapter.py deliberately masks close/EOS until4096 or5000 and injects synthetic pressure through the policy function. Verify exact cue positions and normal final completion. This is an artificial boundary check,not real queue-pressure validation or quality evidence. Failure stops;raw evidence stays preserved;no automatic retry.
3. Calibration:separate proposed2h outer/100m inner cap,eight requests:two disjoint pairs at4K and the same pairs at8K. Hash-ranked selection,not outcome selection. Inspect actual queue occupancy,telemetry freshness,completion and injection delays. Generate proposed-trace.json and stop.
4. Freeze and review:check whether intended workloads actually create slack,congestion and recovery. Freeze trace bytes/hash,code,resource envelope and interpretation before measurement. If load recipe needs revision,version it before measurement,not after unfavorable results.
5. Pilot:72requests,one seed per question,one trace per condition;provisional6h outer/340m inner cap subject to calibration review. Requires an explicit reviewed trace path. No automatic next stage.

Actual GPU execution,private API behavior,KV/cache continuity,queue freshness,port availability and service times remain unverified by CPU tests. Original request-local control logic is copied unchanged;new adapters/policy are separately named. Historical scientific results stay unchanged.

## Paired workload recipe

T=maximum latency of four paired8Kcalibration observations;relative deadline1.5T. This is a scale parameter,not a service-distribution or capacity estimate. Use12SHA256-rankedAIME2025IDs under salt larb-pressure-v1;seed6222+ID. Every policy receives identical IDs,seeds,offsets,deadlines,and intended horizons within a condition.

- Low:4requests at0,1.25T,2.5T,3.75T.
- Near:8requests spaced.4T.
- Burst/recovery:two at0;six at.5T with.05second spacing;four at4T,5.25T,6.5T,7.75T.
- Horizon=last scheduled arrival+relative deadline. Drain separately;no overlapping outstanding requests between phases.
- Rotate policy order by condition:4K/8K/live,8K/live/4K,live/4K/8K. One repetition does not establish counterbalancing or robust statistical evidence.

## Accounting and failure conditions

Primary:correct normally completed answers before scheduled-arrival-relative deadlines per fixed observation minute. Report numerator/horizon alongside accuracy,deadline misses,latencies,tokens,interventions,injection lag,and observed queues. Mean/max/p95 are descriptive with tiny samples. GPU utilization is not instrumented;do not claim utilization gains.

Raw text/IDs,prompts,references,executed sources,versions and GPU metadata are saved;partial stream evidence is retained. Answer caps,missing outputs and ambiguous extraction stay failures. Review wrong/flagged outputs before interpreting accuracy. Client injection lag>1s invalidates a phase and stops without automatic retry. Failures stop later phases;analysis recovers unstarted measured-phase denominators from the frozen trace. Incomplete phases are not valid matched-policy comparisons. Do not terminate requests merely for missing a scientific deadline;drain within the resource cap. Whole-job timeout is a coverage failure,not a policy win.

## What a result would and would not show

Look for8K-like behavior under actual slack and better correct on-time goodput during congestion,with recovery for subsequent admissions. Fixed4K may win. A72-request development pilot is not an independent generalization study:allAIME2025data are development data,conditions have4/8/12requests per policy,and a fresh set plus repeated traces/seeds is needed for stronger claims. A positive result still needs the arrival-only control to isolate live-intervention value.
