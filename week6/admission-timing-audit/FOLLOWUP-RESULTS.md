# Arrival-only ablation and two-block follow-up report

**Execution succeeded; live intervention did not demonstrate a repeatable advantage in correct on-time answers.** It matched arrival-only on the pooled primary count while reducing output tokens and latency, at the expense of fewer correct answers overall. Do not advance a claim of goodput superiority from this study.

Job 6791535 completed November 4, 2026, 04:36:13–09:15:22 Eastern in **4h39m09s** (exit 0). Both blocks retained one H100 80GB allocation, each with a fresh engine and separate real-queue/recovery gate. The six-hour outer cap was sufficient, leaving 1h20m51s. No GPU switch occurred; the failed deadline SSH inspection did not change the queued job. The original two cancelled allocations produced no responses and were not included.

## Coverage and audit

**168/168 responses:** 160 measured + 8 probes; zero missing, zero inference retries. All 20 phases fully drained with valid injection timing. The two four-request mechanics gates passed independently; all executed-source hashes and both frozen traces match. The saved summaries were reproduced exactly from the collected executed analysis code in separate CPU output directories, and request-level token/cue/admission/deadline arithmetic was checked against raw records. All caps remain failures in the planned denominators.

Source-lock SHA256: `a7872f0e29e6a55cf13e9bed69ef33bcfad69e1a3e16fb265ffc0bbe5ebea0cc`.

Block 0 trace: `f9055320b436d64c8a55f1439b74040d6876bd9511bdaa904f4020f3021330bd`.

Block 1 trace: `8fd2f5758ef06ef49bcde732716dade78630ff9da1e5ba99f0f290d7f6b34ab1`.

The allocation wrapper was also preserved and its SHA256 matched `07b4e8c56d4466b6a0faf876554251cf1d589ecc36ea9214eb9a08662db540f8`. Slurm's six-hour limit superseded the original submission's 12-hour ceiling without changing scientific settings. Both manifests record H100 80GB, driver 615.71.09, vLLM 0.11.2, torch 2.9.0, and Transformers 4.57.6.

## Report the two blocks before pooling

Each block has 20 measured responses per policy (8 near + 12 burst). Block 0 uses seed base 6222; block 1 uses 16222 and reversed policy orders. Same 12 development questions and fixed timing recipe.

| Block | Policy | Correct | Correct on time | Deadline misses | Mean latency | Output tokens | Caps |
|---|---|---:|---:|---:|---:|---:|---:|
| 0 | fixed4k | 6/20 | 5/20 | 1 | 112.1s | 107,878 | 6 |
| 0 | fixed8k | 9/20 | 6/20 | 5 | 224.0s | 184,332 | 4 |
| 0 | arrival | 9/20 | 6/20 | 4 | 189.3s | 170,486 | 5 |
| 0 | live | 8/20 | 7/20 | 2 | 137.3s | 144,370 | 3 |
| 1 | fixed4k | 4/20 | 3/20 | 2 | 111.7s | 111,935 | 9 |
| 1 | fixed8k | 8/20 | 6/20 | 4 | 212.2s | 183,701 | 6 |
| 1 | arrival | 7/20 | 5/20 | 4 | 204.6s | 173,354 | 6 |
| 1 | live | 5/20 | 4/20 | 2 | 144.1s | 142,976 | 8 |

Against arrival-only, live gains one correct on-time answer in block 0 (7 vs 6), then loses one in block 1 (4 vs 5). Against fixed 8K, live goes from 7 vs 6 to 4 vs 6. The primary advantage therefore reverses across blocks. Live's latency/token reductions versus arrival-only occur in both blocks, but overall correctness is lower in each (8 vs 9 and 5 vs 7).

## Pooled descriptive results

Forty measured responses per policy. Common observation horizons sum to 4,269.555 seconds (71.16 minutes) per policy across both blocks. This metric denominator is distinct from actual GPU allocation duration. A good answer must be correct, normally completed, and inside both its scheduled deadline and common horizon.

| Policy | Correct overall | Correct on time | Goodput/min | Deadline misses | Mean latency | Output tokens | Caps |
|---|---:|---:|---:|---:|---:|---:|---:|
| fixed4k | 10/40 | 8/40 | 0.1124 | 3 | 111.9s | 219,813 | 15 |
| fixed8k | 17/40 | 12/40 | 0.1686 | 9 | 218.1s | 368,033 | 10 |
| arrival | 16/40 | 11/40 | 0.1546 | 8 | 197.0s | 343,840 | 11 |
| live | 13/40 | 11/40 | 0.1546 | 4 | 140.7s | 287,346 | 11 |

Live versus arrival-only: **same 11 correct on-time answers**, **16.4% fewer output tokens**, **28.5% lower mean latency**, and deadline misses 8→4. Overall correct answers fall 16→13. Live maximum latency is 286.4s versus arrival-only 393.3s; these are sample maxima, not tail-population estimates.

Live versus fixed 8K: **11 vs 12 correct on-time**, **21.9% fewer tokens**, **35.5% lower mean latency**, and misses 9→4. Overall correctness falls 17→13. The one-answer primary deficit is descriptive and is not established as statistically reliable. Fixed 4K is cheapest and fastest but returns only 8 correct on-time answers. No policy dominates every objective.

## Conditions: where the differences arise

| Block | Condition | Policy | Correct | Correct on time | Mean latency | Tokens | Live cuts |
|---|---|---|---:|---:|---:|---:|---:|
| 0 | near | fixed4k | 2/8 | 2/8 | 95.2s | 45,162 | 0 |
| 0 | near | fixed8k | 3/8 | 2/8 | 195.1s | 73,951 | 0 |
| 0 | near | arrival | 2/8 | 2/8 | 163.0s | 72,910 | 0 |
| 0 | near | live | 3/8 | 3/8 | 110.5s | 59,772 | 5 |
| 0 | burst | arrival | 7/12 | 4/12 | 206.8s | 97,576 | 0 |
| 0 | burst | live | 5/12 | 4/12 | 155.2s | 84,598 | 3 |
| 0 | burst | fixed4k | 4/12 | 3/12 | 123.3s | 62,716 | 0 |
| 0 | burst | fixed8k | 6/12 | 4/12 | 243.2s | 110,381 | 0 |
| 1 | near | live | 1/8 | 1/8 | 119.8s | 57,848 | 5 |
| 1 | near | arrival | 2/8 | 2/8 | 181.9s | 73,153 | 0 |
| 1 | near | fixed8k | 3/8 | 3/8 | 163.5s | 71,866 | 0 |
| 1 | near | fixed4k | 2/8 | 2/8 | 81.9s | 45,306 | 0 |
| 1 | burst | fixed8k | 5/12 | 3/12 | 244.6s | 111,835 | 0 |
| 1 | burst | fixed4k | 2/12 | 1/12 | 131.6s | 66,629 | 0 |
| 1 | burst | live | 4/12 | 3/12 | 160.4s | 85,128 | 3 |
| 1 | burst | arrival | 5/12 | 3/12 | 219.8s | 100,201 | 0 |

Burst/recovery: live, arrival-only and fixed 8K tie on correct on-time answers in **each** block (4/12, then 3/12). Live changes which questions succeed: versus arrival-only, it gains question 19 and loses question 23 in block 0; gains 19 and loses 26 in block 1. Thus equality of aggregate counts does not imply preserved per-question answers. Near: live versus arrival-only changes from 3 vs 2 to 1 vs 2. This is not a stable primary benefit.

## Controller mechanics and pressure evidence

Sixteen measured live cuts (eight per block: five near, three burst), plus four probe cuts. Arrival-only and fixed-budget phases have **zero** live cuts. All 168 initial budgets match the saved admission-time waiting rule; every cut uses a causal same-phase scheduler snapshot with the request active, preserves the request-local output object, and begins the exact cue at max(4096, tokens already produced). Later cuts do not rewind generated tokens. The maximum audited pressure age at a cut is 18.1ms.

Near fixed 4K has zero waiters in both blocks. Near fixed 8K maximum waiting is 2 then 1; arrival-only 1 then 2; live 1 in both. Burst maximum waiting is 6 under all four policies in both blocks. Both real-queue probes show waiting/cuts and an 8K recovery admission without a live cut. No scheduler preemptions were observed. Maximum injection lag was 101.8ms, below the frozen 1s limit. Queue-step counts are telemetry, not time-weighted utilization or GPU-efficiency measurements.

## Extraction and capped outcomes

There are **47 measured answer caps** (4K 15, 8K 10, arrival-only 11, live 11), plus three probe caps. All 50 are preserved and counted as unsuccessful; there are no missing responses. The review queue covers all 104 measured failures plus eight probe failures.

Six normally completed measured outputs have noncanonical final boxes: 4230 vs reference 113; an expression ending in 69 vs 259; 8279 vs 113; 1465 vs 293; 4240 vs 113; and 6017 vs 106. All are substantively wrong, including the expression that would evaluate to 69. One probe similarly answers 4423 vs 259. No extraction-only correction is warranted.

Of the measured caps, 42 lack a complete final box, four have noncanonical boxes (a fraction or repeated factorial product), and one has an ordinary wrong integer box. No capped response has a canonical reference-matching box; regardless, the frozen protocol would retain a cap as failure. Raw final text and hashes are retained in extraction-review.json. No favorable regrading or rerun occurred.

## Interpretation and next decision

The central mechanism question now has an informative answer: **changing running requests adds a repeatable efficiency benefit over admission-only shortening on these traces, but no repeatable gain in correct on-time answers.** The extra cuts also reduce overall answer correctness. Fewer deadline misses alone is insufficient evidence of greater useful throughput.

Recommended next action: **pause additional GPU submissions and choose the research objective explicitly.** If it remains superior correct-on-time goodput, this controller has not earned a larger evaluation; do not tune deadlines or thresholds on these outcomes and call it confirmation. If an efficiency/latency tradeoff is valuable, preserve the current rule and predeclare a small fresh-question evaluation with fixed 4K/8K and arrival-only controls, a correctness guardrail, and independently chosen load/deadline conditions. Do not expand this same AIME2025 search or claim significance from one extra answer. A fresh evaluation proposal should be reviewed before any new allocation.

These are 12 unique development questions repeated across conditions and seeds, not 40 independent questions per policy. Seed, policy order and run timing co-vary between the two blocks; both share one retained GPU allocation, so they are not independent machine-level replications. Shared queues couple outcomes. No naive per-response significance test or population-generalization claim is justified. Low load was excluded prospectively from this follow-up, and no new broad claim about slack behavior is made. The prior Stage 3 is contextual evidence, not pooled here because it lacks arrival-only and has a different condition mix.

## Preserved artifacts

- original-evidence.tar.gz: original remote result tree, both exact executed source snapshots, raw token arrays, worker/scheduler/server logs, wrapper and Slurm log.
- independent-audit.json: source/trace/gate audits, block and pooled metrics, paired wins/losses, queue/cut evidence.
- independent-analysis/block0 and block1: separate CPU reproductions; original summaries were not modified.
- response-metrics.csv: block-prefixed response identities; probes remain separately labeled.
- token-audit.json and extraction-review.json: full coverage of caps and failed/flagged extraction.
- collection-receipt.json and evidence-sha256.json: provenance and file integrity.

No new GPU job or background monitor was launched. The one-time switch checkpoint had already been deleted after its SSH failure.
