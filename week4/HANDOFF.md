# Current Week 4 handoff

## State and ownership

Checkpoints **1A–1C, 2A–2C, and 3A–3C are complete**. Packaging/hand-off work for 7A is complete; reserved evaluation and closest-method comparison remain outstanding. Branch: `main`. The branch tip is the single consolidated commit; use `git rev-parse HEAD` to identify it. No person has claimed the next checkpoint; update this file when taking it.

All new implementation, configurations, reports, and essential evidence are under [step1/](step1/README.md). Week 3 imports are unchanged by this work. Read [packaging provenance](step1/PACKAGING.md) before comparing original source paths or historical commit identifiers.

## Verified evidence

- CPU: 21 policy/adapter tests, six metric tests, trace replay checks, and eight deliberate validator corruptions pass. Exact commands: [step1 README](step1/README.md).
- Real concurrency gate: job **6440402**, H100 80GB, 24 requests, **176/176 checks passed**; binding live cutoff followed by complete cue and normal answer. [Gate report](step1/admission-control/REPORT.md).
- Controlled comparison: job **6440653**, same engine/hardware across policies, two reverse-order blocks, 96 measured outcomes and two calibration requests. Complete raw coverage and provenance audited. [Final report](step1/controlled-comparison/REPORT.md).
- Correct on time /24: full 7, arrival 8, admission 8, live 12. Eventual correct /24: 22, 20, 22, 24. All 24 admission/live initial budget pairs match. One binding live cutoff per block; no parser or infrastructure errors. Two full-thinking cap failures remain counted.
- Cases support earlier capacity release and four queued deadline rescues. A repeated eventual quality gain has divergent sampled prefixes; it does not establish improved reasoning from interruption.

These are two replays of **12 exposed development questions**, not 24 independent accuracy examples. No held-out guarantee, other traffic condition, or novelty claim is established.

## Jobs, resources, and retrieval

**No active jobs and nothing left to collect.** Do not resubmit either completed experiment to reproduce analysis.

Renewed successful jobs used 1:16:37 (1.277 GPU-hours). Including two zero-request setup failures: **1:20:56 (1.349 GPU-hours)**. No policy tuning or inference retries occurred in the comparison. Full failed-attempt evidence remains at the original PACE paths indexed in each saved attempt's `archive-index.json`.

PACE: `ssh yzheng609@login-ice.pace.gatech.edu`; root `~/scratch/CS6222-qwen3-baseline`. Original results: `week4/admission-control/results/job-6440402/` and `week4/controlled-comparison/results/job-6440653/`. Git stores lossless event archives and complete successful run records at their new paths under `week4/step1/`; original source snapshots retain original names.

## Next concrete action

**Begin 5A: audit question exposure before proposing reserved questions and traffic.** Retain the current candidate without tuning to this development result. Read Week 3 exposure records, choose eligible questions only after checking their history, and save a new frozen evaluation plan with traffic conditions, paired order, deadlines, uncertainty, and a realistic compute limit. Do not launch an unplanned campaign. Closest-method comparison (Task 6) remains unresolved.

## Session update template

Replace current state above when handing off; keep run history in result directories. Record: checkpoint/owner/branch; changes and rationale; verification commands and outcomes (CPU versus GPU); configuration/output paths; active job IDs plus collection commands or explicitly none; unresolved issues; allocated compute; one next action. Push the updated handoff with code and evidence.
