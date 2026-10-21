# Current Week 4 handoff

## State and ownership

Checkpoints **1A–1C, 2A–2C, and 3A–3C are complete**. Packaging/hand-off work for 7A is complete; reserved evaluation and closest-method comparison remain outstanding. Branch: `main`. The implementation was consolidated in commit `4e3bbe4`; later documentation and privacy cleanup keep the results unchanged. The next checkpoint is available for someone to pick up.

All new implementation, configurations, reports, and essential evidence are under [step1/](step1/README.md). Week 3 imports are unchanged by this work. [Packaging notes](step1/PACKAGING.md) explain source paths, historical commit identifiers, and privacy cleanup.

## Verified evidence

- CPU: 21 policy/adapter tests, six metric tests, trace replay checks, and eight deliberate validator corruptions pass. Exact commands: [step1 README](step1/README.md).
- Real concurrency gate: job **6440402**, H100 80GB, 24 requests, **176/176 checks passed**; binding live cutoff followed by complete cue and normal answer. [Gate report](step1/admission-control/REPORT.md).
- Controlled comparison: job **6440653**, same engine/hardware across policies, two reverse-order blocks, 96 measured outcomes and two calibration requests. Complete raw coverage and provenance audited. [Final report](step1/controlled-comparison/REPORT.md).
- Correct on time /24: full 7, arrival 8, admission 8, live 12. Eventual correct /24: 22, 20, 22, 24. All 24 admission/live initial budget pairs match. One binding live cutoff per block; no parser or infrastructure errors. Two full-thinking cap failures remain counted.
- Cases support earlier capacity release and four queued deadline rescues. A repeated eventual quality gain has divergent sampled prefixes; it does not establish improved reasoning from interruption.

These are two replays of **12 exposed development questions**, not 24 independent accuracy examples. No held-out guarantee, other traffic condition, or novelty claim is established.

## Jobs, resources, and retrieval

**No active jobs and nothing left to collect.** The saved records are enough to reproduce the analysis.

Renewed successful jobs used 1:16:37 (1.277 GPU-hours). Including two zero-request setup failures: **1:20:56 (1.349 GPU-hours)**. No policy tuning or inference retries occurred in the comparison. Each saved setup attempt includes a diagnosis and an index of the original file hashes. Successful runs are fully included in Git.

Successful run records are included in Git under `week4/step1/`, including compressed events, inputs, grades, and executed source snapshots. Local cluster login and workspace settings are intentionally omitted; the launchers accept local environment configuration.

## Next concrete action

A useful next step is **5A: check question exposure, then plan reserved-question and traffic validation**. The current development result supports keeping the candidate as it is. Week 3 exposure records can help identify eligible questions; a new plan can set traffic conditions, paired order, deadlines, uncertainty, and a realistic compute budget. Closest-method comparison (Task 6) also remains open.

## Session update template

A short update here can help the next person, with detailed run history left in result directories. Useful details include: checkpoint/owner/branch; changes and rationale; verification commands and outcomes (CPU versus GPU); configuration/output paths; active job IDs plus collection commands or explicitly none; unresolved issues; allocated compute; one next action. Sharing the updated notes with the related code and results keeps the context together.
