# Initial findings and current limits

## 1. Native training pilot

AReaL + vLLM + Qwen2.5-1.5B-Instruct, actual calculator TIR, two H200 GPUs. First eight updates plus checkpoint evaluation:

| Native setting | Elapsed | Held-out answer success, before → after |
|---|---:|---:|
| Lookahead2 / concurrency16 |96.2s|60.9% → 60.2%|
| Lookahead2 / concurrency8 |237.8s|63.3% → 50.0%|
| Fresh gating |268.3s|60.9% → 32.0%|

Scheduling settings affect execution and quality. The strongest tested native setting preserves accuracy better and completes faster. **No positive learning per GPU-hour was demonstrated.** These are single training runs, with only32 held-out prompts/four candidates each. Tools are optional for these math questions; this is not evidence of improved tool-dependent agent ability.

## 2. Rollout-to-learner diagnosis

First eight updates, excluding evaluation from the recorded stage sums:

| Setting | Dispatcher batch-collection time | Rollout share of recorded non-evaluation stages |
|---|---:|---:|
| Wide async |48.46s|57.1%|
| Capped concurrency |130.66s|78.4%|
| Fresh gating |235.46s|90.6%|

In wide async, the batch returns a median13.4ms after its last member finishes. Every post-initial collection begins with fewer than the eight completed groups required. Batch acquisition matters, but those seconds are not automatically scheduler-recoverable. Wide concurrency improves both observed token throughput and mixed-group delivery; the hypothesized opposition between them is not observed here.

Wide's collection time falls6.06 → 2.08 → 0.96s/update across successive eight-update windows, alongside changing policy/tool behavior. Early waiting cannot be extrapolated across training.

## 3. Executed GroupGate comparison

Fixed-policy actual inference,16 identical source prompts/four candidates each per arm, one Blackwell48GB MIG instance, one engine, full drain, same mixed-group filter.384 comparison episodes plus16 preflight episodes completed; all group/filter checks passed.

| Arm, execution order | Drained wall time | Accepted mixed groups | Time to8 mixed groups |
|---|---:|---:|---:|
| Native |34.13s|12|29.50s|
| FIFO16 |37.95s|10|34.02s|
| GroupGate16 |37.85s|12|16.89s|
| FIFO8 |48.67s|8|48.66s|
| GroupGate16 repeat |41.17s|9|32.21s|
| FIFO16 repeat |43.49s|11|26.69s|

GroupGate made16 and18 non-FIFO admissions. Its first time-to8 improvement reversed on repetition. Even repeated identical policies differed in15–16 of64 terminal outcomes despite stable per-request seeds, so small differences cannot be confidently attributed to scheduling.

The external gate queued up to47 requests. Native vLLM reached62 running requests with no sampled waiting requests or preemptions; peak observed KV occupancy stayed below3%. Low KV occupancy does not measure compute utilization, and2-second sampling can miss short queues. Nevertheless, our extra cap created queueing while removing native parallelism. Native had the shortest observed cohort time, though it was measured once and cache order differs between arms.

Cost of this comparison allocation, including cold startup:757s =0.2103 MIG-instance-hours, **not full-GPU hours**. No learner or weight updates ran in this comparison.

## Research decision

Keep the broader coordination question open, but do not scale up this exact fixed-cap priority design on current evidence. A useful revision would preserve native feasible parallelism and prioritize only at an observed binding resource/admission constraint. That revision has not been built or validated.

Remaining gaps: consequential residual inefficiency beyond tuned baselines; the correct control point; reproducible mechanism benefit; reliable positive learning on a genuinely tool-dependent workload; end-to-end learning/freshness results; differentiation from nearby systems and generality. Existing related papers neither establish our gap nor rule out an improved design.
