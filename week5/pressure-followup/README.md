# Week 5 follow-up: quality headroom → queue-pressure control

**Current handoff:** Stage 3 completed and all 76 records were independently audited. Live adaptation tied fixed 8K on correct on-time answers while reducing latency and tokens; it did not demonstrate primary goodput superiority. Read the [Stage 3 report](STAGE3-REPORT.md). The two follow-up allocations were cancelled before execution ahead of cluster maintenance; neither produced responses. No job or monitor remains active. See the [follow-up plan](FOLLOWUP-PLAN.md). Snapshot: November 2, 2026; see [STATUS.json](STATUS.json).

This folder packages the essential evidence and portable preparation from the follow-up work. It is deliberately small: compact response metrics, checkpoint features and grouped-validation results, CPU reproduction, the FIFO correction, and serving code/protocol. Full raw generations, token arrays, cluster logs, private account configuration, and machine-specific paths remain outside this public handoff. The portable serving copy has a new layout and source hash; it is **not** the exact executed GPU bundle. Executed-source hashes are documented in the stage reports.

## How this builds on the other Week 5 work

| Existing work | What it contributed | What this follow-up adds |
|---|---|---|
| [Builder report](../builder/REPORT.md) and [one-waiter design](../builder/one-waiter/PLAN.md) | A real in-flight budget controller and evidence that triggering at the first waiter can reduce congestion latency | A harder quality workload, explicit 4K/8K controls, and a staged experiment focused on correct answers delivered before deadlines |
| [Explorer targeting](../explorer/targeting.py) | Shadow decisions about which active request to cut to help waiting deadlines | A correction to FIFO lane reuse, documented and tested separately in [fifo/](fifo); the new queue-count policy does not depend on this estimator |
| [Earlier controller](../../week3/larb/serving-proof/control.py) | Request-local cue, token-cap, and row-movement mechanics | A separately versioned policy with 8K under slack and reductions toward 4K under observed queue pressure |

The question has sharpened: **can queue-pressure adaptation deliver more correct answers on time than a sensible fixed budget?** We do not need to predict mathematical correctness to ask it. We also do not assume the adaptive policy will win.

## What we learned

The initial 12-question screen and untouched 18-question remainder cover all 30 AIME2025 questions, two seeds and four budgets: **240/240 responses**, no inference retries. The remainder reproduced the direction of the longer-budget advantage. [RESULTS.md](RESULTS.md) separates that confirmation from subsequent development-only routing studies.

| Fixed thinking allowance | Correct / 60 | Accuracy | Mean output tokens | Mean isolated time |
|---|---:|---:|---:|---:|
| 2K | 18 | 30.0% | 3,536 | 40.7s |
| 4K | 22 | 36.7% | 5,460 | 62.9s |
| 8K | 27 | 45.0% | 8,748 | 100.4s |
| 16K safety reference | 31 | 51.7% | 12,741 | 146.1s |

Longer computation has quality value here, but costs substantially more. Lightweight lexical routing did not capture that value well: the 2K router was dominated by fixed 4K, and the 4K router retained only 20% of the incremental 4K→8K gain. We closed this rule family rather than expanding thresholds on the same questions. An answer-aware oracle shows opportunity, not an achieved policy.

## Completed stages and what comes next

```mermaid
flowchart LR
    A[240-response budget screen complete] --> B[Lightweight routing unsuccessful]
    B --> C[Stage 1 mechanics passed]
    C --> D[Stage 2 calibration complete]
    D --> E[Stage 3: goodput tie, efficiency gains]
    E --> F[Arrival-only comparison and repetitions planned]
    F --> G[Cancelled before execution for maintenance]
    G --> H[Review environment and authorize a future restart]
```

Stage 1 verified exact cue boundaries at 4,096 and 5,000 tokens under synthetic masks. Stage 2 calibrated timing with eight real requests. Stage 3 independently audited all 76 records, including four probes and 72 measured responses. These are completed results; the original preparation protocol remains a historical specification.

Across the 24 measured responses per policy, fixed 4K delivered **6** correct on-time answers, fixed 8K **7**, and live control **7**. Live used **15.7% fewer output tokens** and reduced mean latency **26.7%** relative to fixed 8K. This is an efficiency result, not demonstrated goodput superiority. Read [STAGE3-REPORT.md](STAGE3-REPORT.md) for condition-specific outcomes, caps, extraction review, and limitations.

The next comparison adds arrival-only control and two matched development blocks: **160 measured responses plus eight probes**. Both allocations were cancelled at the user's request before starting, ahead of the announced maintenance. There are no follow-up measurements to interpret. The [frozen follow-up plan](FOLLOWUP-PLAN.md) explains how it would isolate admission decisions from changes to running requests. After service restoration, verify the existing runtime and storage before considering a separately authorized restart. No automatic restart or monitoring is configured.

## Discussion: what should change our mind?

Use these questions for the next review; record the decision and evidence in [DISCUSSION.md](DISCUSSION.md).

1. **After mechanics:** did the realized cue positions and cap semantics match the contract, including the request already beyond 4K?
2. **After calibration:** do our intended load conditions actually produce slack, waiting, and recovery? A maximum of four latency observations is a scaling device, not a capacity estimate.
3. **After the pilot:** does live control beat both fixed budgets on correct on-time goodput, or merely reduce tokens? If fixed 4K wins, should we prefer that simpler policy?
4. **If live wins:** does the benefit require changing running requests? An arrival-only control is implemented but must be explicitly added before attributing gains to live intervention.
5. **Before broader claims:** what fresh problems and repeated traces/seeds should confirm the result? All AIME2025 traces are now development data.

## Reproduce the compact evidence (CPU only)

From the repository root:

```sh
python3 -B week5/pressure-followup/analysis/reproduce.py
python3 -B -m unittest discover -s week5/pressure-followup/fifo -p 'test_*.py'
python3 -B week5/pressure-followup/serving/readiness.py
```

The first command reproduces the fixed-budget aggregates and both question-grouped selectors from compact derived records. It does not recreate the original inference or independently re-audit raw answer extraction. The latter commands verify the correction and portable policy/workload/accounting tests. [evidence/](evidence) contains the supporting tables and validation folds; [BUNDLE.md](BUNDLE.md) explains provenance and privacy boundaries.
