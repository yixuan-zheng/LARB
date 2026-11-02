# Stage 2 calibration report

**Decision: calibration is valid for timing and asynchronous-service preparation. Proceed to Stage 3 only with a real-queue/recovery gate before the measured matrix. No Stage 3 job has been submitted.**

## Execution and integrity

November1,2026,22:05:48–22:19:39 Eastern;H10080GB;8CPUs;64GBhostRAM. Slurm exit0,total **13minutes51seconds**,including preflight,engine startup and four paired phases. All **8/8** raw responses are collected;all four phases drained and passed injection-lag checks. No retries,package changes,or extra stages.

The executed source-lock hash remains0f30a3bf38721e5e5d7a2965eda46b92b17828d641e0789e8fa64e01e3276caf. Collected source hashes match. The independent CPU audit confirms exact cue positions,Eos/close structure,legacy answer-cap classification,and integer grades for all eight records. The proposed trace exactly reproduces the predeclared recipe using calibration latencies alone. Original evidence is preserved privately;sanitized metrics are in [evidence/stage2-calibration.json](evidence/stage2-calibration.json).

## Measured calibration

Hash-ranked IDs11,28,23,26;two disjoint simultaneous pairs under each fixed budget,same question seeds. These are four difficult development questions,not a representative quality evaluation.

| Fixed budget | Responses | Mean latency | Range | Mean output tokens | Normally completed | Answer capped | Correct |
|---|---:|---:|---:|---:|---:|---:|---:|
|4K|4|84.2s|73.4–88.5s|5917|1|3|1|
|8K|4|153.2s|148.0–157.5s|9814|4|0|1|

Observed mean-time ratio8K/4K is1.82;output-token ratio1.66. These are paired asynchronous-serving timings,not the isolated-request baseline. All8Kanswers completed normally,but three are wrong;normal completion is not correctness. The three4Kcaps remain failures. Their outputs have no complete final box. The normally completed wrong8Kanswers explicitly give408vs248,86vs259,and574vs610;no extraction-only correction is justified. These results do not overturn the larger240-response quality screen or justify changing the workload based on correctness.

The shared analyzer prints calibration goodput using1800splaceholder horizons/deadlines. Those numbers are **not** a serving-policy comparison and should not be used as headline findings. Calibration's useful outputs are timings,mechanical accounting and telemetry—not its artificial deadline goodput.

## Telemetry findings

- All four phases reached two scheduled active requests.
- Maximum observed scheduler waiting count was **zero in every phase**.
- Observed preemption counts and live interventions were zero;fixed policies were used.
- Maximum client injection lag was **1.81ms**,well below the1sphase-validity threshold.
- Scheduled-to-first-observed-active delay ranged about5ms–1.52s;the largest was in the first pair. This is an observed scheduling delay,not a pure queue-wait estimate.

The first arrival snapshots were roughly75sold because they preceded the first scheduling step after initialization. Later phase-arrival ages were about0.51–0.53s following idle/drain intervals. Empty idle snapshots are not proof of stale active-pressure control. Conversely,this run cannot establish live pressure freshness because there was no waiting episode. Inspect active-phase scheduler-to-worker event alignment in the next gate rather than imposing an arbitrary age limit based on idle snapshots.

## Proposed workload numbers

T=max observed paired8Klatency=**157.548s**;relative deadline1.5T=**236.322s**.

| Condition | Requests per policy | Frozen recipe | Common horizon per policy |
|---|---:|---|---:|
|Low|4|196.935sbetween arrivals|827.128s(13.79min)|
|Near|8|63.019sbetween arrivals|677.457s(11.29min)|
|Burst/recovery|12|Two at0;six near78.774s;four recovery arrivals starting630.193s|1457.321s(24.29min)|

All three policies share the same IDs,seeds,arrivals,deadlines and horizons within a condition. The nine observation horizons sum to **2h28m06s**. This is a sum of metric denominators,not an exact walltime forecast:phases may drain earlier or finish after their metric horizon.

This recipe is plausible,but calibration does not certify that “near” is near capacity. Two concurrent8Krequests taking about153s suggest an aggregate completion scale of one request per76.6s under steady two-request batching;63sarrivals may create waiting. That is only a rough dimensional check,not a queue simulation or capacity estimate. Prompt heterogeneity and batching can change the result.

## Recommendation

Stage2has passed its bounded objective. Do not rerun difficult outcomes or tune loads to observed correctness. Do not yet treat the72-request matrix as a validated congestion experiment. The missing engineering evidence is a **real waiter triggering the live controller and subsequent recovery**.

The proposed Stage3plan is [STAGE3-PLAN.md](STAGE3-PLAN.md):four explicitly counted queue/recovery probe requests,then the72-request measured pilot only if predeclared mechanics gates pass. This is a proposed76-request scope,not silent authorization to add requests. It requires a new frozen version and explicit Stage3approval. Monitoring remains off;no jobs have been submitted.
