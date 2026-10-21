# Admission control and controlled comparison

The [current handoff](../HANDOFF.md) is the authoritative continuation record. Read the [comparison report](controlled-comparison/REPORT.md) for the result and [gate report](admission-control/REPORT.md) for mechanism validation.

| Location | Contents |
| --- | --- |
| admission-control/ | Policy, vLLM bridge, service, bounded concurrency runner, tests, admission boundary, gate evidence |
| controlled-comparison/ | Frozen plan, matched runner, scoring, cases, figures, complete comparison evidence |
| EXPERIMENT-SESSION.md | Saved resource limits and continuation criteria |
| PACKAGING.md | Relocation, immutable provenance, omitted duplicates, retrieval instructions |

The gate passed 176 checks. Live achieved 12/24 correct-on-time outcomes versus admission 8/24, over two replays of 12 exposed questions. Retain the candidate and prepare reserved evaluation after auditing exposure. No jobs are active.

## Verify without a GPU

Run from the repository root. Python 3.10+ with `aiohttp` is required for replay; scoring additionally needs the pinned dependencies in `week3/larb/stage3/requirements-analysis.txt`. Install them in a separate analysis environment, not the serving environment. Matplotlib is needed only for figures. Do not copy model weights or environments into Git.

```bash
python -B -m unittest discover -s week4/step1/admission-control -p 'test_*.py'
python -B -m unittest discover -s week4/step1/controlled-comparison -p 'test_*.py'
python -B week4/step1/controlled-comparison/checks/check_replay.py
python -B week4/step1/controlled-comparison/checks/pack_events.py --root week4/step1/admission-control/results/job-6440402 --unpack
python -B week4/step1/controlled-comparison/checks/pack_events.py --root week4/step1/controlled-comparison/results/job-6440653 --unpack
python -B week4/step1/admission-control/validate_smoke.py --root week4/step1/admission-control/results/job-6440402
python -B week4/step1/admission-control/checks/check_validator.py --root week4/step1/admission-control/results/job-6440402
python -B week4/step1/controlled-comparison/analyze.py --root week4/step1/controlled-comparison/results/job-6440653
python -B week4/step1/controlled-comparison/checks/check_final_record.py --root week4/step1/controlled-comparison/results/job-6440653
```

Expected: 21 + six unit tests, replay pass, 176 gate checks, eight rejected corruptions, audited complete comparison, and final record checks pass. See component READMEs to regenerate cases and figures. Analysis materializes ignored logs and can rewrite deterministic scored artifacts; keep originals when changing the grading method. No GPU submission is needed for these checks.

## Documentation contract

Use the [Week 4 README workflow](../README.md#how-to-document-and-hand-off-work). Keep handoff state in **week4/HANDOFF.md**, reproducible commands in READMEs, conclusions in reports, and immutable evidence in unique run directories. Avoid parallel handoffs and repeated chronological notes.

Before launching, save a plan and configuration including candidate/source lock, question exposure, trace/deadlines, sampling, hardware/software, policy order, success criteria, analysis, allocation/attempt limits. For every attempt retain inputs, raw outcomes/events (including errors and caps), executed sources/hashes, environment/hardware, scores, validation, and compute accounting. Give revised configurations new identifiers. Compress large evidence losslessly; omitted artifacts need SHA-256 hashes and retrieval paths.

At session end, update the shared handoff using its template, run the checks relevant to changes, verify report numbers against saved machine-readable results, and push code, documentation, and essential evidence together. State what the next person should do first. Never describe CPU fixtures as GPU validation or repeated development questions as independent evaluation examples.
