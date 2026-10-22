# 5B: staged reserved validation

This folder executes the unchanged candidate and the frozen [5A plan](../evaluation-plan/EVALUATION.md). [The collected-stage report](REPORT.md) links current evidence and clearly labels partial results. It contains the sparse pinned input, runner, mechanical audit, scorer, and per-job evidence. The planning-stage “no GPU” field describes 5A; the subsequent 5B execution was authorized on 2026-10-22. No scientific settings or selected questions were changed.

## Stages and limits

The first job, **6481923** (shard 0 late burst), is complete. The timestamped `status.json` and `campaign.json` record subsequent progress. The execution order is shard 0 late burst, shard 0 sustained pressure, shard 0 low load, then the same three conditions for shard 1. The remaining stages are queued with `afterok` dependencies and cancellation of invalid dependencies. A complete mechanical/provenance audit and archive precede advancement; correctness scores and whether cuts occur do not choose later workloads. Each job includes exposed-only calibration and four matched phases. Low load and no-cut outcomes remain part of the campaign.

There are six base allocations, at most four hours each, with one diagnosed infrastructure replacement allowed by the plan (28 GPU-hours maximum including repair). The driver ceiling is 230 minutes, startup allowance 25 minutes, and phase ceiling 45 minutes. The recorded runtime-fit check happens before reserved inference. Jobs stop when complete, so allocated use can be well below the ceiling. No automatic retries are enabled.

## Checks and evidence

From the repo root:

```bash
python3 -B -m unittest discover -s week4/reserved-validation -p 'test_*.py'
python3 -B week4/reserved-validation/preflight.py --local
```

The audit tests reuse the real development records, never reserved answers. They verify the new trace rules and reject deliberately corrupted clocks, cues, and sources. The separate analysis environment pinned in Week 3 is needed for grading:

```bash
python -B week4/reserved-validation/validate.py --root week4/reserved-validation/results/job-JOB_ID
python -B week4/reserved-validation/analyze.py --root week4/reserved-validation/results/job-JOB_ID
```

`validate.py` accepts lossless `.jsonl.gz` scheduler archives. Each result directory retains raw responses, client schedules/receipts, events, immutable trace and plan hashes, source snapshots, input hashes, runtime/hardware, validation, and allocation accounting. The scorer keeps caps and wrong answers in its denominators. Its mechanical gate does not require favorable quality or a live cutoff. When all six jobs are complete, `analyze.py --aggregate RUN1 ... RUN6 --out week4/reserved-validation/analysis` produces the campaign result; an incomplete set is not reported as complete.

The sparse input uses the legacy filename `problems100.json` so the frozen server needs no changes. It has 500 indexed positions, with only the 24 selected rows and calibration rows 0/2 populated. The dataset manifest verifies the public pinned JSONL, all unique IDs, the saved first-100 prefix, and every included row. The separate prompt-overlap audit finds no exact normalized overlap with the development prefix or among selected questions. No other reserved rows are exposed to the server.

## Continuing or collecting

[The handoff](../HANDOFF.md) and [campaign.json](campaign.json) record current job IDs and stage state. Local cluster login and workspace settings stay outside Git; the launcher takes `PACE_PROJECT_ROOT`, `VALIDATION_SHARD`, `VALIDATION_CONDITION`, and `VALIDATION_SOURCE_COMMIT` from the environment. A saved job can be collected and audited without resubmission. New attempts receive new result directories and retain the prior evidence.

Before the campaign, the runtime-project exposure audit found the selected cohort disjoint from recorded generation there as well as in the repo. That saved snapshot describes initial exposure; later stages intentionally repeat the same cohort under the frozen plan. Unrecorded or external runs and model pretraining cannot be ruled out. Once reserved inference starts, those questions are marked exposed even if the attempt fails. No controller tuning or prior-method baseline work uses this cohort.

`collect.py --job JOB_ID` retrieves a completed stage using local `PACE_SSH_TARGET` and `PACE_PROJECT_ROOT` settings. It preserves source/input bytes and lossless scheduler archives, sanitizes private diagnostic paths, and collects allocation accounting. Cluster configuration values are not stored in Git.

CPU-only job **6482012** is queued after the last GPU stage. It grades all six runs, verifies the complete 288-outcome campaign, writes per-job accounting and aggregate results, and uses an isolated pinned analysis target. Its 30-minute CPU ceiling consumes no GPU allocation. Scientific success is not a dependency condition: a negative complete result still reaches grading.

`status.py` reads scheduler/accounting and phase counts using the same local cluster settings. It writes a timestamped, sanitized `status.json`; this is a snapshot, while the Slurm chain can continue after the chat closes. No helper submits duplicate jobs or automatically retries a failed stage.

`watch.py` is an optional local observer in the analysis environment. It reads the existing Slurm chain, collects and grades completed stages, and builds the aggregate once all six are complete. It never submits or retries GPU work. The Slurm chain and CPU grading still operate if the observer or chat closes. `--exclude-analysis` on the collector keeps local grading separate from the independent cluster grading, avoiding concurrent analysis-file copies.
