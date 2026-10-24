# Planning the next evaluation

These notes cover **5A (evaluation planning)** and **6A (closest-method comparison planning)**, prepared on 2026-10-22. They preserve the current candidate and make the next experiments concrete; no new GPU inference or controller changes were made.

At planning time, the repository audit found **100 exposed MATH-500 questions** and **400 provisionally reserved questions**. The validation plan selects 24 by an outcome-independent hash rule, leaving 376 for later work. This is a repository-based exposure check, not a claim about unrecorded runs or model pretraining.

| File | What it helps answer |
| --- | --- |
| [EVALUATION.md](EVALUATION.md) | What will we measure, on which questions and traffic, and within what budget? |
| [plan.json](plan.json) | Exact cohort, order, settings, trace rules, decision criteria, and limits |
| [exposure.json](exposure.json) | Which tracked runs used which indices? |
| [candidate-lock.json](candidate-lock.json) | Which existing controller and grading sources are frozen? |
| [PRIOR-WORK.md](PRIOR-WORK.md) | What do the closest methods already do, and which comparison is feasible? |
| [FEASIBILITY.md](FEASIBILITY.md) | What signals are available for cross-request control, and what experiment would distinguish it? |
| [signal-audit.json](signal-audit.json) | What do the saved intervention events establish? |
| [sources.json](sources.json) | Primary references, inspected sections/code revision, and access limitations |
| [upstream-audit.json](upstream-audit.json) | Why the pinned Dynasor helper needs a stopping-contract review before reuse |

## Reproducing the planning checks

From the repository root, with Python 3.10 or newer:

```bash
python3 -B week4/evaluation-plan/audit.py
```

This checks the frozen cohort and source lock and regenerates exposure, trace examples, signal observations, and [validation.json](validation.json). It uses existing records and reads no selected question prompts or answers. Numeric [trace examples](trace-examples.json) illustrate the rules using the earlier development calibration; the future run will save fresh exposed-only calibration and its numeric traces before measured inference.

The upstream stopping check is optional and separate. Download the public pinned helper to a temporary file, then:

```bash
curl -L --fail 'https://raw.githubusercontent.com/hao-ai-lab/Dynasor/0d2f1b93a60e031cfc7fb43843d2b736b225960c/dynasor/core/entropy.py' -o /tmp/dynasor-entropy.py
python3 -B week4/evaluation-plan/audit_upstream.py --entropy-source /tmp/dynasor-entropy.py
```

The script checks the source hash and evaluates three reviewed pure functions, with simple decimal-string equality. It demonstrates a helper-level discrepancy; it is not a measured comparison with the complete upstream system.

## Picking up from here

5B execution and the [5C assessment](../reserved-validation/REPORT.md) are now complete. The selected 24 questions are exposed, bringing recorded project exposure to 124; the saved planning audit remains the pre-campaign snapshot. The [6B CPU/interface investigation](../laser-feasibility/REPORT.md) is now complete. Its conditional next step is baseline orchestration and a small mechanics gate before any large 6C comparison, without treating the consumed validation cohort as untouched. [The shared handoff](../HANDOFF.md) records current state; a short update there can link any changed plan, checks, active jobs, and next action. Local environment and cluster settings can stay outside these notes.
