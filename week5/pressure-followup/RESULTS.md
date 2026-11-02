# Findings and limits

## Fixed-budget screen and confirmation

Pilot:12 hash-ranked questions ×2seeds ×4budgets =96 responses. Remainder:the untouched18questions under the same protocol =144responses. All outputs present. Remainder accuracy:2K19.4%,4K30.6%,8K36.1%,16K44.4%,versus pilot45.8%,45.8%,58.3%,62.5%. The harder remainder reproduced the longer-budget direction; it is confirmation within one model/task distribution,not broad generalization.

Pooled8K improves15.0points over2K at2.47×mean time;16K improves21.7points at3.59×. Question-cluster bootstrap95%intervals for these gains are[3.3,28.3]and[6.7,36.7]points. Thinking-token budgets are not total-output limits: all settings have a separate2048-token answer allowance and the same forced transition cue. Mean output tokens include both phases. Capped outcomes remain failures. Across60responses per budget,answer caps:18at2K,13at4K,5at8K;thinking caps:25at16K. Quality includes completion behavior under this protocol,not just reasoning quality.

No extraction-only grading corrections were identified in the original raw-output review. All wrong/ambiguous records were retained. The compact CSV retains observed final extraction,reference,finish category,correctness,tokens,and time; original raw text is not included here. Interpret references and observations as preserved measurements,not independent solution proofs. Dataset question11 includes raw Asymptote code rather than a rendered diagram.

## Negative lexical-router studies

| Development study | OOF accuracy | Mean time | Interpretation |
|---|---:|---:|---|
|2K→8K router|35.0%|70.7s|Fixed4K is faster and more accurate; expected cost-matched mixing also better|
|4K→8K router|38.3%|67.4s|Only one of seven possible rescues captured;20%gain retention versus80%target|

Question-grouped leave-one-question-out selection keeps both seeds together. Rules see only checkpoint features; reference answers,future tokens,IDs,and final outputs do not enter decisions. Family definitions and fold selections are in evidence/. Full-data rule scores are development-only. Successive exploration on the same30questions means cross-validation is not independent confirmation.

At4K,candidate-answer markers identify some already-correct requests but do not separate rescuable from persistently wrong requests. Correction phrases are common in both groups. Random extension at the same count averages37.7%accuracy,versus router38.3%;53%of random assignments equal or exceed that router. The tiny point difference is not convincing selection value. No GPU implementation was justified.

## Why a queue study still makes sense

All56requests still thinking at4K have matching4096-token prefixes under4K/8K;four early-completed outputs match fully. Endpoint categories:20correct at both,7rescued,31wrong at both,2regressions. A hidden-answer oracle extending seven rescues reaches29/60(48.3%)at67.6s. This is an optimistic ceiling,not an implementable method. The rescues are concentrated in four questions; the4K→8K accuracy-difference bootstrap interval includes zero.

The serving mechanism can instead respond to reliable system demand. It should retain long budgets during slack,shorten eligible open thinking under waiting pressure,and allow future admissions long budgets after recovery. The primary measure is correct normally completed answers before deadlines per fixed observation minute. Lower latency or fewer tokens alone is not success.

A72-request development pilot is small:one trace per condition and one seed per question. Four low-load requests cannot establish reliable quality preservation. Arrival-only adaptation is needed before claiming a distinct benefit from intervening mid-generation. GPU utilization is not currently sampled; do not claim utilization gains. Timing comparisons require matched hardware and serving conditions.

The controller's FIFO correction is independent:fixed-lane estimates are not a vLLM batching model,and the new pressure rule does not consume them. Historical Week5 explorer outputs are not rewritten by this handoff.
