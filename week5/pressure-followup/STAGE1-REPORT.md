# Stage 1 GPU mechanics report

**Decision: PASS for synthetic transition mechanics. Recommend proceeding to Stage 2 calibration only.** No calibration or measured pilot has been submitted. Monitoring remains disabled at the user's request.

## Execution

November 1, 2026,20:10:20–20:17:03 Eastern;H10080GB;8CPUs;64GBhostRAM;one-hour allocation cap. Slurm completed with exit0 in **6minutes43seconds**,including runtime preflight,model initialization and two synthetic generations. The generation step occupied3minutes44seconds including engine startup. These are engineering timings,not workload throughput measurements.

The executed bundle hash matches the approved frozen source lock:

`0f30a3bf38721e5e5d7a2965eda46b92b17828d641e0789e8fa64e01e3276caf`

The portable source under serving/ is a relocated handoff with its own hash;it was not the bundle executed in this job. Existing model/runtime revisions were preserved:vLLM0.11.2,torch2.9.0,Transformers4.57.6,Qwen3-4B revision1cfa9a7208912126459214e8b04321603b3df60c. No upgrades or inference retries.

## Observed boundary checks

| Case | Synthetic pressure begins | Initial →reduced thinking budget | Actual cue starts | Total generated tokens | Outcome |
|---|---:|---:|---:|---:|---|
|Below4K|64|8192→4096|4096|5170|Normal completion|
|Already beyond4K|5000|8192→4096|5000|6207|Normal completion|

Worker events independently show one synthetic cut and one cue start for each request. The first request waits until4096before cueing. The second starts its cue at its existing5000-token position,without pretending the already-generated tokens disappear. Thinking closes12tokens into the exact14-token cue in both cases;that offset is expected and is not an overshoot bug. Both outputs end in normal EOS and stay within the preserved legacy2048-token answer allowance,including its trailing-cue accounting.

## Evidence verification

Collected the full existing result directory and Slurm log into a new private local collection. Independently checked:

- Exactly two synthetic raw records,with no missing or capped outcome.
- Exact cue token subsequences at4096and5000,one thinking-close token per output,and final EOS.
- Matching synthetic_gate_cut and cue_started worker events at expected positions.
- Manifest/source-lock identity and every executed source hash.
- Completed Slurm state,exit0,and gate.json passed=true.

The original raw records,worker events,executed sources,and cluster logs remain preserved privately. The public summary is [evidence/stage1-mechanics.json](evidence/stage1-mechanics.json);account names,job identifiers and operational paths are omitted. The earlier15package tests also passed on the allocated runtime;the independent FIFO correction has14CPUtests.

## What this establishes

The new budget rule can change the request-local state inside the real vLLM logits-processing path and force the intended cue at both a future4Kboundary and the current position of an already-late request. The normal answer phase survives both transitions. That resolves the immediate boundary-mechanics risk sufficiently to justify the next small engineering stage.

## What remains untested

The gate deliberately masks close/EOS to hold thinking open and supplies synthetic pressure. It does **not** test a waiter causing the real asynchronous scheduler to trigger a cut. The two cases run sequentially;they do not validate multi-request row movement,preemption,KV-cache continuity under contention,or real recovery. Natural closure and already-answering exclusions have CPU tests,but were not independently exercised by these forced-open GPU cases. It also provides no mathematical accuracy,deadline-goodput,or cross-policy performance evidence.

## Stage 2 recommendation

**Go to the separately scoped eight-request calibration,not the72-request pilot.** Use the same frozen operational bundle and H100 setup;proposed2h outer cap with100m inner guard. Run two disjoint paired question groups at fixed4Kand fixed8K,eight requests total. Budget roughly15–40minutes plus variability;this is an estimate,not a deadline guarantee. Preserve all outputs and stop on infrastructure/coverage failure without automatic retries.

Accept Stage 2 only after checking async-service startup and version/API compatibility,scheduler/worker telemetry association and freshness,expected request count,token-cap/completion accounting,injection lag,and actual paired service times. Calibrated timings may generate a proposed trace but must not automatically launch measurement or tune to correctness outcomes.

**Important limit:**two-request calibration phases at max_num_seqs2 are not designed to create a waiting queue. They estimate paired service time and exercise instrumentation;they cannot prove that the proposed low/near/burst workload produces meaningful congestion or that the live queue trigger works. Before committing to the full measured matrix,we should separately specify a tiny real-queue smoke probe or an explicit preliminary workload-validation gate. Its extra requests must be counted and authorized;they are not silently part of the eight-request calibration.

After calibration,review the proposed arrival/deadline scale and resource envelope. Confirm actual queue formation and recovery before interpreting any measured pilot. If the intended near-capacity workload shows no waiting,report that classification failure rather than treating it as evidence for or against adaptive control. A positive pilot still needs an arrival-only comparator before attributing benefit specifically to in-flight intervention.

## Current handoff

Stage1:completed and independently verified. Stage2:recommended,not submitted. Stage3:unsubmitted,conditional on calibration/workload review. No monitor has been re-enabled. The pending-status text in the earlier handoff is superseded by this report.
