# Stage 3 report: queue-pressure budgets under matched load

## Decision

**The engineering run succeeded;the primary goodput-superiority objective was not demonstrated.** Live adaptation tied fixed8K on correct on-time answers,while reducing tokens and latency. It beat fixed4K by only one on-time correct answer overall. Treat this as a promising efficiency characterization,not a validated goodput improvement or reason for a large rollout. The most useful next study is an arrival-only ablation plus repeated matched traces;no follow-on job has been launched.

## Execution,coverage and independent verification

November2,2026,00:52:56–03:13:42 Eastern;oneH10080GB,8CPUs,64GBhostRAM. Slurm completed with exit0 in **2h20m46s**,inside the6hcap. **76/76** records are preserved:four engineering probes and72measured responses,all11phases fully drained. No failure,retry,missing request,or automatic extra stage. Max client injection lag98.8ms,below the1svalidity limit. Monitoring remained disabled;this was a one-off collection at the user's request.

Independent CPU analysis reproduced the original summary exactly in a separate output directory. Verified all raw EOS/close/cue/cap contracts,worker-cut events,request-local output-object identity,source hashes and trace identity. The real-queue gate was reproduced independently;its check-list order was normalized for comparison because set iteration order is not deterministic. Original evidence and summaries were not modified.

Executed source-lock SHA256:`e30dbed1bb503d415a22246b59959f8646a572322c7483322da9bd13770a4a78`
Trace SHA256:`e80f0f4dc56735eefd2232117c312c0df5fa3bb2f28937abda2e3189a3ae6a98`

The trace bytes match the calibrated proposal and were frozen before probes/measurement. Scientific server,controller,sample,seeds,budgets,cue,threshold,deadline and grading were unchanged from the approved setup. This was a new operational bundle adding the real-queue gate and scoped timeout/accounting checks;the older portable serving handoff is not the executed Stage3bundle.

## Primary results by workload

Deadline236.322sper request from scheduled arrival. Common per-policy horizons:low827.128s,near677.457s,burst1457.321s. Only correct normally completed answers before both deadline and horizon earn goodput. Capped answers remain failures even if terminated by the cap's EOS.

| Condition | Policy | Correct | Correct on time | Deadline misses | Mean / max latency | Output tokens | Live cuts |
|---|---|---:|---:|---:|---:|---:|---:|
|low|fixed4k|0/4|0/4|0|87.5/99.2s|22,776|0|
|low|fixed8k|0/4|0/4|0|148.0/154.1s|39,212|0|
|low|live|0/4|0/4|0|152.0/169.1s|39,212|0|
|near|fixed8k|3/8|3/8|0|164.7/210.8s|71,115|0|
|near|live|3/8|3/8|0|120.1/155.9s|62,942|5|
|near|fixed4k|3/8|3/8|0|80.9/87.6s|44,847|0|
|burst|live|6/12|4/12|2|160.7/279.9s|83,829|3|
|burst|fixed4k|4/12|3/12|1|125.7/250.9s|62,716|0|
|burst|fixed8k|6/12|4/12|4|238.3/493.5s|110,381|0|

### Low load

No waiting and no cuts under any policy. Live produced **identical token sequences to fixed8K for all four requests**. That is a useful noninterference observation under slack,but all four questions were wrong under every policy,so this condition does not establish preserved high accuracy. Fixed4K was cheaper and faster with the same zero successful answers. The cohort is not replaced retrospectively.

### Near condition

The intended pressure condition occurred:fixed8Kmax waiting2;live1;fixed4K0. All policies delivered3/8correct on time,and none missed a deadline. Live reduced mean latency27.0%and tokens11.5%versus8K,but fixed4K was still fastest and cheapest with the same observed success count. No deadline-goodput improvement occurred here. Aggregate equality hides answer swaps:live gains question21and loses question29relative to8K.

### Burst and recovery

All policies reached a six-request waiting queue. Live delivered4/12correct on time,the same as8K,and one more than4K. Live and8K both had6/12overall correct;4K had4/12. Versus8K,live reduced **mean latency32.6%**,**maximum latency43.3%**,and**output tokens24.1%**;deadline misses fell4→2. This is the clearest practical efficiency result. It does not improve the primary goodput numerator over8K. Fixed4K had the lowest mean latency and only one deadline miss,but fewer correct on-time answers.

The live/8Kgoodput tie is not identical per-request success:live gains question19and loses question23. Versus4K,live gains questions25and24but loses question1due to lateness:two wins,one loss,one net additional on-time answer. Avoid inflating that small count into a robust relative-percent superiority claim.

## Across the three conditions

Each policy sees24responses across the same12unique questions,with repeated questions/seeds across conditions. The common horizons sum to2961.906s(49.37min)per policy. This is a metric denominator,not allocated GPU time or a walltime forecast.

| Policy | Overall correct | Correct on time | Goodput / min | Deadline misses | Mean latency | Total tokens | Answer caps |
|---|---:|---:|---:|---:|---:|---:|---:|
|fixed4k|7/24|6/24|0.1215|1|104.4s|130,339|6|
|fixed8k|9/24|7/24|0.1418|4|198.7s|220,708|4|
|live|9/24|7/24|0.1418|2|145.7s|185,983|6|

Relative to8K,live retains the observed9correct and7correct-on-time responses while reducing mean latency**26.7%**and tokens**15.7%**. Relative to4K,it buys two more correct answers and one more correct on-time answer at39.6%higher mean latency and42.7%more tokens. This is an observed tradeoff on this trace,not evidence that live dominates both fixed policies. Token savings are a compute proxy;no GPU-utilization,energy,billing or throughput-per-actual-allocation claim was measured.

## Did the controller do what we intended?

The real-queue probe passed:one waiter was observed,two eligible running requests were cut,exact cues began at4096,and a later empty-queue request was admitted at8192without a cut. One probe answer was capped;it was preserved and excluded from the72measured denominator,not retried or used to select the workload.

Eight live cuts occurred during measurement:five near,three burst;none low. All cuts link to the same scheduler snapshot with real waiters,the request is active in that snapshot,and output-object identity is preserved. Recorded pressure ages at all ten cuts(including probes)are about1.7–5.2ms. No observed preemptions. These are useful telemetry checks,not a comprehensive KV-cache or performance proof.

Near cuts occurred at4263,7325,4352,7791,and4374thinking tokens. Bursts cut two already-late requests at5164/5165and one newly admitted request before any thinking at0,with its cue later at4096. “Reduce toward4K” never rewinds generated tokens:late cuts transition immediately at the current position.

In burst-live,five requests also received4K at admission. All four recovery arrivals were admitted at8192,had no live cut,and cued at8192. Thus pressure response and recovery occurred,but the burst result combines admission-time decisions and mid-generation intervention. An arrival-only comparator is needed to separate their contribution.

## Answer extraction and capped outcomes

All76raw records and token arrays were audited,including four probes. There were **16measured answer caps**(4K6,8K4,live6)plus one capped probe. All remain failures. Three capped outputs contain an integer box,but those integers are also wrong;there is no hidden correct completed answer to recover.

The review queue has47measured failures plus four probe failures. Four normally completed outputs were flagged as noncanonical because their boxed answers exceed the dataset's three-digit integer range:4144vs113,4218vs113,4532vs113,and1465vs293. These are wrong answers,not formatting-only false negatives. Fourteen capped outputs lack complete boxes;ordinary wrong integer outputs are direct reference mismatches. No grading correction was made. All raw review text and hashes are preserved privately;the public compact metrics expose no cluster identity or operational paths.

## Limits on interpretation

This is one hardware setup,one seed per question,one trace/order per condition,and only12unique development questions. The24responses per policy are not24independent questions. AIME2025has already been inspected repeatedly. Shared queue interference also couples outcomes across requests. We therefore do not attach a population-significance claim or a naive question-bootstrap confidence interval to this single-trace systems result. Independent repeated arrival traces/seeds are needed for uncertainty assessment.

Budget interventions alter batching and numerical execution;matched seeds do not guarantee identical trajectories under different pressure. Low-live/8Ktoken identity is observed for these four cases,not assumed universally. The data show quality/completion changes in some directions,not deterministic preservation of specific8Kanswers. Question11still uses dataset diagram code without rendered image. P95from4/8/12samples is not a reliable tail-population estimate;maximum latency is reported descriptively instead.

## Recommendation and next research decision

**Do not launch a large evaluation yet.** The predeclared claim that live should beat both fixed baselines on correct on-time goodput was not met. Preserve the frozen deadline/load settings and unfavorable outcomes;do not tune a new deadline on this run and relabel it confirmation.

A small follow-up is justified by the burst latency/token reduction with equal observed8Ksuccess counts. Highest-value next steps:

1. Add the already implemented **arrival-only policy** under matched workloads. This isolates whether live cuts add value beyond shortening new admissions under pressure. Keep fixed4K/8Kcontrols.
2. Repeat a small predeclared set of burst/near traces and seeds,with rotated/randomized policy order. Judge count differences over independent runs rather than this one extra answer. Keep diagnostic analysis separate from evaluation selection.
3. Before broader quality/generalization claims,pin fresh problems and a separate evaluation protocol. Improve the low-load quality test through a predeclared fresh sample,not by swapping out these four failures.
4. If arrival-only matches live,prefer the simpler mechanism unless live has a clearly measured extra benefit. If fixed4Kconsistently wins primary goodput,accept that result.

No new GPU job or monitor has been started by this report. Stage3is complete and collected.

## Artifacts

Public:[stage3-results.json](evidence/stage3-results.json),[stage3-response-metrics.csv](evidence/stage3-response-metrics.csv). They include gate,condition/pooled metrics,paired count differences,telemetry and cap classifications. Full original archive,Slurm/server/scheduler/worker logs,executed sources,independent reanalysis,token audit and extraction-review records are retained in the private local result collection. The compact public evidence does not independently reproduce raw-answer grading without those originals.
