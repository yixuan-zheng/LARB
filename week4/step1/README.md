# Admission control and controlled comparison

The [handoff](../HANDOFF.md) is a quick introduction for whoever picks this up next. The [comparison report](controlled-comparison/REPORT.md) explains the findings, and the [gate report](admission-control/REPORT.md) covers mechanism validation.

| Location | Contents |
| --- | --- |
| admission-control/ | Policy, vLLM bridge, service, bounded concurrency runner, tests, admission boundary, gate evidence |
| controlled-comparison/ | Frozen plan, matched runner, scoring, cases, figures, complete comparison evidence |
| EXPERIMENT-SESSION.md | Saved resource limits and continuation criteria |
| PACKAGING.md | Relocation, immutable provenance, omitted duplicates, retrieval instructions |

The gate passed 176 checks. Live achieved 12/24 correct-on-time outcomes versus admission 8/24, over two replays of 12 exposed questions. The results support trying reserved evaluation with the current candidate, after checking question exposure. No jobs are active.

## Verify without a GPU

Run from the repository root. Python 3.10+ with `aiohttp` is required for replay; scoring additionally needs the pinned dependencies in `week3/larb/stage3/requirements-analysis.txt`. A separate analysis environment keeps scoring dependencies apart from serving. Matplotlib is needed only for figures.

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

## Sharing progress

The [Week 4 overview](../README.md#leaving-notes-for-the-next-person) describes how the notes fit together. A brief update to `week4/HANDOFF.md` can cover the current checkpoint, changes, checks and their outcomes, result paths, open questions, active jobs (if any), compute used, and a suggested next action.

For a new experiment, a saved plan makes later interpretation easier: candidate and source hashes, question exposure, traffic and deadlines, sampling, hardware/software, policy order, success criteria, analysis, and a realistic compute budget. A separate result directory for each attempt keeps configurations, raw responses/events, scores, checks, and accounting together—including failures.

Reports are most useful when their numbers link back to saved results and distinguish CPU checks, GPU validation, and development findings. Repeated questions are still the same accuracy examples. A short explanation of these limits is more helpful than a long activity log.
