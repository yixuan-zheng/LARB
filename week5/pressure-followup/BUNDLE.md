# Bundle contents,provenance,and privacy

Essential public artifacts only:

- evidence/response-metrics.csv:240derived response rows;no raw prompts,generations or cluster metadata.
- evidence/:separate pilot/remainder/pooled summaries,checkpoint feature tables,rule specifications,fold selections,and oracle bounds.
- analysis/:reproduces aggregates and grouped rule decisions from compact derived data. It does not independently reproduce tokenizer decoding or raw-answer grading.
- fifo/:corrected copy and14tests. The existing explorer files and historical outputs are not overwritten by this folder. The old estimator assigned waiters to original lanes instead of reusing the earliest-freed lane. Example:availability10/90s,service40s gives completions50/90/130/130/170s;the old second prediction was130s.
- serving/:portable controller,service,harness,analysis,synthetic gate,tests,spec,and explicit source-freeze utility. No account configuration,upload helper,job-submission caller,cluster log,or queued-job identifier.
- screen/:minimal integer-extraction library and pinned problem input needed by the portable service. Dataset MathArena/aime_2025,revision and declaredCC-BY-NC-SA-4.0license are retained in inputs/manifest.json. Respect that license for the dataset material;this file does not relicense it.

Original full run records and exact raw-output audits are kept locally rather than duplicated into this handoff. Compact result tables retain capped outcomes and strict grading;they cannot prove extraction correctness without the original raw evidence. No inference result is recomputed or improved by packaging.

Executed GPU source hashes in the stage reports are retained for provenance. Relocated paths and portable readiness code change this public copy's hash. Never substitute one hash for the other or claim this portable copy was GPU tested. Source-lock.json uses repository-relative paths,not private filesystem paths. Runtime evidence snapshots may contain local operational paths when executed later;keep generated results private and sanitize separately before publication.

Scientific claims do not require personal account names,login hosts,private home/scratch paths,absolute local paths,or Git credentials. Those are excluded. STATUS.json is a dated manual handoff,not a promise the job remains pending when read later. Monitoring is disabled; the latest two follow-up jobs were cancelled before execution. Stage reports and the follow-up plan distinguish completed measurements from unexecuted work.
