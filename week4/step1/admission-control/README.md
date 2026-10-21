# Step 1: admission-only and live control

New implementation and evidence live here; Week 3 sources/results are unchanged.
**Current state:** 1A/1B/1C passed. Real job 6440402 passed all 176 GPU checks;
the controlled comparison is complete. See [the report](REPORT.md).
Read [the admission boundary](ADMISSION-BOUNDARY.md) for the verified dispatch
path. This folder implements checkpoint 1, not the controlled quality comparison.

- `w4_policy.py`: one pure admission rule, fixed arrival decisions, live-only
  reductions. Defaults: short 2,048; long 16,384; two waiting requests.
- `w4_adapter.py`: annotate first-scheduled request metadata before dispatch;
  initialize workers from it; reuse Week 3 scheduler auditing and cue forcing.
- `w4_server.py`: four policy modes in one streaming engine; raw token records.
- `run_smoke.py`, `spec.json`, `run_smoke.sbatch`: one saved late-burst trace,
  six exposed development questions per mode, one engine/allocation, no retries.
- `validate_smoke.py`: offline mechanical audit, with explicit failed checks.
- `checks/`: CPU test output and pinned-runtime source inspection.
- `results/job-JOB_ID/`: immutable attempts, inputs, executed sources, hashes,
  package inventory, hardware, raw responses, client progress, and events.

Run CPU checks from the repository root:

```bash
python3 -B -m unittest discover -s week4/step1/admission-control -p 'test_*.py' -v
```

The 21 CPU tests include the scheduler-to-worker bridge using engine-shaped
fixtures. They establish same-input admission/live initialization, fixed
admission budgets, live-only changes after progress, phase isolation, row moves,
resumption retention, natural closure, full cue completion, and cap semantics.
They do not establish GPU operation.

PACE uses the existing `~/scratch/CS6222-qwen3-baseline/vllm-proof-env`, pinned
cached model, and unchanged historical imports. Only the `week4/` subtree is
uploaded. Source-lock verification rejects mismatched imported dependencies.
The first job failed in packaging verification (14 allocated seconds); its
replacement hit a four-minute startup guard (245 allocated seconds). Both
generated zero requests. See the [bounded repair plan](REPAIR-PLAN.md).
The user then authorized realistic startup/inference margins. Job 6440402 used
the current 45-minute allocation ceiling, 40-minute driver cap, and 20-minute
startup allowance, and passed after 18:13. See the renewed
[session plan](../EXPERIMENT-SESSION.md). All four modes shared one allocation.
Other compatible hardware requires an explicit launcher/configuration change
before submission, recorded with the run.

For a future bounded run, first read the handoff and record the next attempt's
limit. Then submit from `~/scratch/CS6222-qwen3-baseline`:

```bash
sbatch --output=week4/step1/admission-control/results/slurm-%j.out week4/step1/admission-control/run_smoke.sbatch
```

Collect the submitted job; do not submit another copy. After collection:

```bash
python3 -B week4/step1/admission-control/validate_smoke.py --root week4/step1/admission-control/results/job-JOB_ID
```

The GPU gate requires four completed modes, admission metadata before generation,
overlap and a genuine late burst, fixed admission-only budgets, a binding live
cutoff after generated progress, the exact cue followed by answer continuation,
and no cap/error failures. The fixed trace is for engineering validation, with
no deadlines, grading, quality claims, or policy-order performance inference.
Failure is preserved and diagnosed; the test is not automatically retried.
`checks/check_validator.py --root RUN_DIRECTORY` checks eight intentional
corruptions of temporary copies. All eight were rejected on the real passing
baseline; see `checks/validator-regressions.json`.

## Recording future work

Follow the [documentation contract](../README.md#documentation-contract). Record each attempt and its resource limit before submission, then update the shared [handoff](../../HANDOFF.md) with checks, job status, output paths, and one next action. Successful run events are compressed: use `../controlled-comparison/checks/pack_events.py --root RUN_DIRECTORY --unpack` before validation. Earlier failed attempts retain concise evidence and SHA-256 retrieval indexes; see [packaging](../PACKAGING.md).
