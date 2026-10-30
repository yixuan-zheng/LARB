# Week 5 results layout

Each condition of the Week 5 plan is one run directory under `job-<allocation>-<condition>/`:

| File | Contents |
| --- | --- |
| `plan.json`, `cohort.json`, `source-lock.json`, `problems100.json`, `stage3-protocol.json`, `dataset-manifest.json` | Frozen inputs as launched |
| `manifest.json` | Allocation/job id, condition, executed source hashes, runtime versions, engine settings, wall-clock cap |
| `hardware.txt`, `model-files.txt`, `requirements-executed.txt` | GPU, model file sizes and index hash, executed pip freeze |
| `sources/` | Byte copies of every locked source file at launch |
| `server.log` | vLLM engine log |
| `progress.json` | Per-phase client rows, rewritten atomically as requests finish |
| `trace.json`, `trace-freeze.json` | Calibrated arrivals/deadline frozen before measurement |
| `requests/<key>.json` | Raw output, token ids, timing, arrival decision per request |
| `worker.jsonl`, `scheduler.jsonl`, `service.jsonl` | Admission decisions, live reductions, cue events, scheduling snapshots |
| `run-complete.json` or `run-failed.json` | Coverage actually achieved, skipped phases, failure reason |
| `mechanical-validation.json` | Mechanical/provenance audit result |
| `analysis/` | Graded rows, per-policy summaries, paired per-question table, review queue |

Runs, in the order they were produced:

| Run | Condition | Answers | Note |
| --- | --- | --- | --- |
| `job-6663679-gate` | gate | 6 | mechanics gate, session 1; not science |
| `job-6663679-constant_pressure` | constant_pressure | 48 | cohort positions 0–5, complete |
| `job-6665417-gate` | gate | 6 | gate re-run in session 2 under the edited harness; not science |
| `job-6665417-one_at_a_time` | one_at_a_time | 48 | positions 6–11, complete, 8/8 phases |
| `job-6665417-slack_rush_recovery` | slack_rush_recovery | 45 | positions 12–20, 5 of 8 phases: block 0 complete, block 1 only `live_one` |

A run directory is never overwritten: `launch.sh` refuses to start if the target exists. Any
truncated run says so in `run-complete.json` (`skipped`) and in the coverage audit.

Failed attempts are kept beside the successful runs with an explicit name. None of them produced a
measured answer.

| Attempt | What stopped it |
| --- | --- |
| `attempt1-…-startup-failed` | the previous condition's engine still held 65.6 GB, so the server never became ready |
| `attempt2-…-trace-bug`, `attempt3-…-cohort-key-bug` | runner stopped after calibration on two key-name bugs in `execution.trace_for` |
| `attempt4-…-engine-oom` | the gate's `EngineCore` survived the launcher's `pkill` and left only 14.5 GB free (`one_at_a_time`) |
| `attempt5-…-engine-oom` | the same orphaned engine (`slack_rush_recovery`) |
| `attempt6-…-recap-before-cap` | started by a watchdog, then stopped when the cap was re-planned |
| `attempt7-…-wrong-allocation-label` | started without `SLURM_JOB_ID`, so it wrote into a directory labelled 6662944 |
| `attempt8-…-cap-too-tight` | 3,300 s cap would have skipped the fourth phase, i.e. `live_one` would never have run |

## Executed launchers

`../launch.executed-v1.sh` is byte-for-byte the launcher that produced the session-1 gate and the
pressure run. It was revised afterwards (anchored `pkill`, `EXIT` trap, refuse-to-overwrite,
non-fatal audit exit) because a terminated server left its `EngineCore` holding 65.6 GB of GPU
memory and because `set -e` skipped cleanup when the audit returned non-zero. Each run directory
also keeps its own copy of every executed source under `sources/`.

`../session2.sh` is the session-2 chain: gate, `one_at_a_time`, then `slack_rush_recovery` in one
4-hour interactive allocation, each condition with its own measured-phase cap computed from the
remaining wall clock. Its log is `../session2.log`.
