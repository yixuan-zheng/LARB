# Current Week 4 handoff

## State and ownership

Checkpoints **1A–1C, 2A–2C, and 3A–3C are complete**. Packaging/hand-off work for 7A is complete; reserved evaluation and closest-method comparison remain outstanding. Branch: `main`. The implementation was consolidated in commit `4e3bbe4`; later documentation and privacy cleanup keep the results unchanged. 5A and 6A planning was prepared on 2026-10-22 in [evaluation-plan/](evaluation-plan/README.md). 5B is now running as a staged campaign; 6B baseline integration has not begun.

The completed implementation and evidence are under [step1/](step1/README.md); the new validation/research plans are under [evaluation-plan/](evaluation-plan/README.md). Week 3 imports are unchanged by this work. [Packaging notes](step1/PACKAGING.md) explain source paths, historical commit identifiers, and privacy cleanup.

## Verified evidence

- CPU: 21 policy/adapter tests, six metric tests, trace replay checks, and eight deliberate validator corruptions pass. Exact commands: [step1 README](step1/README.md).
- Real concurrency gate: job **6440402**, H100 80GB, 24 requests, **176/176 checks passed**; binding live cutoff followed by complete cue and normal answer. [Gate report](step1/admission-control/REPORT.md).
- Controlled comparison: job **6440653**, same engine/hardware across policies, two reverse-order blocks, 96 measured outcomes and two calibration requests. Complete raw coverage and provenance audited. [Final report](step1/controlled-comparison/REPORT.md).
- Correct on time /24: full 7, arrival 8, admission 8, live 12. Eventual correct /24: 22, 20, 22, 24. All 24 admission/live initial budget pairs match. One binding live cutoff per block; no parser or infrastructure errors. Two full-thinking cap failures remain counted.
- Cases support earlier capacity release and four queued deadline rescues. A repeated eventual quality gain has divergent sampled prefixes; it does not establish improved reasoning from interruption.

These are two replays of **12 exposed development questions**, not 24 independent accuracy examples. No held-out guarantee, other traffic condition, or novelty claim is established.

## Development evidence and resources

The completed development runs under `step1/` used **1.349 GPU-hours**, including two zero-request setup failures. Their raw records, compressed events, grades, source snapshots, and setup diagnoses are included in Git. This accounting is separate from the active 5B campaign below. Local cluster settings stay outside Git.

## New planning results (2026-10-22)

- **5A:** Before 5B, the tracked-record audit found indices 0–99 exposed and treated 100–499 as provisionally reserved. The saved hash rule selects 24 questions, leaving 376 separate. The later prepared-runtime audit found no additional recorded exposure; unrecorded or external exposure remains unknown. [Evaluation design](evaluation-plan/EVALUATION.md), [exact plan](evaluation-plan/plan.json), [exposure evidence](evaluation-plan/exposure.json).
- The unchanged admission/live candidate is compared on low load, late burst, and sustained pressure, in two blocks and two question shards: 288 measured outcomes plus 12 excluded calibration requests. The base maximum is 24 GPU-hours, or 28 with one diagnosed infrastructure replacement. These are campaign ceilings; planning itself used no GPU allocation. Numerical traces are frozen after fresh exposed-only calibration and before reserved inference.
- **6A:** LASER is the selected closest load-aware adaptation target, with fixed-threshold probing and the current pair as controls. The pinned public Dynasor helper fails three consistency-contract cases; this is a scoped upstream-code observation, not a measured result against the full system. ACER's abstract is relevant, but its restricted full text leaves an algorithm-level novelty gap. [Comparison plan](evaluation-plan/PRIOR-WORK.md), [CPU evidence](evaluation-plan/upstream-audit.json).
- The development trace shows about 9.7 seconds from binding cue start to final completion. Deadline transport and remaining-work/answer-reserve estimates are missing online signals. [Feasibility notes](evaluation-plan/FEASIBILITY.md) distinguish a simple deadline guard from a possible downstream-benefit selector. Neither is implemented.
- Offline planning checks pass: cohort/exposure disjointness, exact candidate hashes, three trace rules, saved event-derived observations, and the six-case upstream audit. Reproduce with `python3 -B week4/evaluation-plan/audit.py`; the optional upstream audit command is in its README. No reserved prompts/answers were inspected or generated during selection.

## 5B execution (2026-10-22)

The unchanged candidate and frozen plan run under [reserved-validation/](reserved-validation/README.md), using source commit `fd2fa46`. The input and exposure audits, eight runner/audit tests, and a scorer check against the saved development results passed before execution. The initial prepared-runtime audit covered 811 recorded generation files and found only indices 0–99; it cannot rule out external or unrecorded runs.

Six GPU jobs form a serial after-success chain: **6481923 → 6481975 → 6481976 → 6481977 → 6481978 → 6481979**. Each has a four-hour ceiling; one diagnosed infrastructure replacement is allowed within the 28 GPU-hour total ceiling. Mechanical validation and archival gate continuation; correctness does not. CPU-only grading job **6482012** follows the final GPU stage, using an isolated pinned analysis environment. No controller or baseline development is mixed into this evaluation.

## Current collection state

Two of six stages are collected and graded. Shard 0 late burst ties at **7/24 correct on time, 23/24 eventual correct** for both policies. Shard 0 sustained pressure yields **13/24 admission versus 17/24 live on time**, with **24/24 versus 23/24 eventual correct**. Both stages passed their mechanical audits; these are still only 12 unique questions, repeated across conditions/blocks. The low-load shard-0 job **6481976** is now running; shard-1 jobs remain dependency-gated. No controller or trace settings changed after seeing these outcomes.

## Next concrete action

The local `watch.py` observer collects and grades completed stages while the pre-submitted Slurm chain continues independently. Collect the next low-load stage without shortening its scheduled arrival spacing. The six-job [ledger](reserved-validation/campaign.json), [status snapshot](reserved-validation/status.json), and [partial report](reserved-validation/REPORT.md) record progress. Only all six complete matched jobs support the final 288-outcome aggregate. Failures halt the chain without automatic GPU retries; a specifically diagnosed replacement remains bounded by the saved total ceiling.

## Session update template

A short update here can help the next person, with detailed run history left in result directories. Useful details include: checkpoint/owner/branch; changes and rationale; verification commands and outcomes (CPU versus GPU); configuration/output paths; active job IDs plus collection commands or explicitly none; unresolved issues; allocated compute; one next action. Sharing the updated notes with the related code and results keeps the context together.
