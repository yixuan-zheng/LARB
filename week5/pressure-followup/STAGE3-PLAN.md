# Stage 3 proposal: real-queue gate + paired development pilot

Status:plan only. **Not submitted.** Proposed scope expands the old72-request pilot to **76requests total:4engineering probes +72measured responses**. The extra probes are separate from the scientific denominator. Approval must cover this scope;do not execute or automatically advance based only on this document.

## Decision and research question

Proceed with queue-pressure adaptation after passing calibration,but first establish that a real waiter can trigger the new controller. The synthetic gate tested in-flight cue boundaries;calibration tested paired fixed-budget serving. Neither tested real waiting-driven cuts or recovery.

Question:under matched arrival traces,does live4K/8Kpressure control improve correct normally completed answers before deadlines compared with fixed4Kand fixed8K? The result can favor a fixed budget. Do not tune policies or deadlines after measured outcomes.

## A. Four-request real-queue/recovery engineering gate

Proposed implementation,not yet frozen or GPU verified:

1. Use the first three hash-ranked calibration IDs11,28,23 with the existing seeds under the live policy. Submit together against max_num_seqs2 so a third request can wait. No synthetic close/EOS masks;no future-answer features. Preserve raw outputs and all scheduler/worker events.
2. Require an actual same-phase waiting episode,at least one eligible running-request reduction,and a corresponding exact cue at max(4096,current thinking position),without rewinding or resetting the answer allowance. Check state/key association across observed row moves and ensure requests already closed/cued are not changed. Validate each termination according to its actual normal-or-cap contract;an answer cap is retained and does not by itself invalidate this mechanical probe. Correctness is not a gate criterion.
3. Fully drain;verify the previous phase has no active requests. Send the fourth hash-ranked ID26 as a separate recovery request with an empty queue. It must be admitted at8192and receive no live reduction unless new real pressure occurs(which should not occur in this single-request recovery phase).
4. Pass only on observed mechanics,complete saved records,valid token accounting,and acceptable injection behavior. If no waiting/cut occurs,the gate is inconclusive/fails its purpose;stop and preserve evidence rather than automatically adding more requests or rerunning.

Use a new versioned runner with a dedicated probe mode. Do not edit the already-executed operational bundle or claim the current runner implements this gate. Define automated checks and tests before freezing. A passing gate may permit the measured phases in the **same allocation** only if that entire76-request sequence is explicitly approved beforehand. A failed/inconclusive gate stops the job;no automatic retry or measured launch.

## B. Seventy-two measured requests

Keep the predeclared scientific recipe and threshold unchanged:

- Policies:fixed4K,fixed8K,live;arrival-only excluded from this pilot.
- Conditions:low4requests,near8,burst/recovery12,each under all three policies.
- One seed per question,identical IDs/seeds/arrival offsets/deadlines within each condition.
- T157.54816743s;deadline236.32225114s. Low spacing196.93520929s;near spacing63.01926697s;burst at78.77408371s,six arrivals spaced0.05s;recovery at630.19266972,827.12787901,1024.06308829,1220.99829758s.
- Orders:low4K/8K/live;near8K/live/4K;burst live/4K/8K. Drain before changing phase. Prefix cache remains off. No reference-answer information enters routing or load construction.
- Freeze trace JSON and SHA256,new source lock,resource settings and gate checks before submission. A new source version must explicitly record changes limited to probe orchestration and operational timeout coverage;do not alter the measured sample,budgets,deadline recipe,threshold,cue or grading.

## Measurements and predeclared interpretations

Primary:correct normally completed answers by their scheduled-arrival-relative deadlines per fixed observation minute. Report raw counts and horizon,not only ratios. Secondary:overall correctness,deadline misses,output tokens,latencies with small-sample warnings,injection lag,queue occupancy,preemptions,and cuts by actual token position. GPU utilization is not currently sampled;make no utilization claim unless instrumentation is explicitly added before freeze.

Check realized load labels honestly:

- Low should show little/no waiting and no live cuts. Any pressure means the intended slack condition was not achieved;report it,do not discard it.
- Near should show meaningful waiting under at least one fixed baseline. If none appears,the intended congestion comparison is inconclusive;do not quietly retune and rerun.
- Burst should show a real queue/cuts and later recovery admissions at8Kwhen pressure is absent. Fixed4Kmay still produce better deadline goodput.

Only a live policy that improves goodput over both fixed baselines in informative pressure conditions,without an unacceptable quality loss,earns a larger study. A few responses of difference are preliminary,not statistical confirmation. Do not demand every condition favor live. If promising,next add arrival-only control to isolate the value of mid-generation changes,then repeated traces/seeds and separately pinned fresh problems. AllAIME2025data remain development data.

## Resource envelope and operational changes to review

Propose oneH10080GB,8CPUs,64GBhostRAM,6houter cap,340mininner guard. Practical expectation roughly2–3hours plus startup/probe variability;the metric horizons total2h28m,but are not walltime guarantees.

The original1800sper-phase drain setting yields a loose nine-phase upper envelope of **6h22m39s before startup/probe**,so it cannot guarantee complete coverage inside6h. Do not present it as fitting the allocation.

Propose an explicitly versioned **1200sdrain allowance after the final scheduled arrival per measured phase**,with the corresponding per-request timeout tested. That gives a nine-phase envelope of **4h52m39s**;allow15minfor the probe,10minfor async startup and5minfor CPUpreflight,about5h23moverall,under the340minguard. These are operational guards,not scientific deadlines. A guard timeout stops execution and leaves planned denominators intact;no retry or favorable-cell replacement. If actual code cannot enforce this accounting,the package is not ready to submit.

No scientific request is aborted merely because it misses its deadline. Preserve partial stream evidence on infrastructure failure. Missing/capped outcomes stay failures;unstarted phases remain in planned counts. Independently reproduce analysis and review extraction after collection. Calibration's artificial1800sdeadline goodput is not a baseline for this study.

## Readiness before go

- [x] Synthetic boundaries4096/5000passed on H100.
- [x] Eight-request paired async calibration collected and independently audited.
- [x] Timing-only trace recipe reproduced exactly.
- [ ] Implement/test real-queue/recovery probe and its automatic gate.
- [ ] Test scoped timeout accounting and partial-stage denominator handling.
- [ ] Freeze new source/trace/resource hashes and CPU readiness result.
- [ ] Review and explicitly approve the76-request Stage3scope.
- [ ] Submit once and record actual job ID;do not reuse a completed allocation.

No automatic monitor is currently enabled. Decide monitoring behavior explicitly at submission rather than silently overriding the user's prior request to disable it.
