# Week 5 — choosing the path (A lane: builder)

Week 5 asks one question that decides the semester: does thinking past 2,048 tokens ever buy a
better answer on this task, and if it does, can the server recover fixed-2,048 congestion
efficiency by cutting at the **first** waiting request instead of the second? This folder is the
whole A-lane workstream (implementation, mechanics gate, GPU runs, collection and scoring); the
frozen design and the sessions it was run in are in [one-waiter/PLAN.md](one-waiter/PLAN.md).

Everything in `week5/builder/` belongs to this one workstream. The sibling folders
[`../explorer/`](../explorer) and [`../pressure-followup/`](../pressure-followup) are separate,
independent workstreams and are not part of this branch.

**Read the [report](REPORT.md)** for the measured result and the three verdicts (premise, fix,
targeting ingredients). Everything is reproducible from the commands below without touching a GPU.

| Path | What it is |
| --- | --- |
| [REPORT.md](REPORT.md) | What was built, the gate, the three workloads, verdicts, limits, engineering record |
| [one-waiter/PLAN.md](one-waiter/PLAN.md) | Frozen design, cohorts and their per-condition slices, traces, analysis rules, session scale |
| [one-waiter/code/](one-waiter/code) | Policy module, serving adapter, runner, launchers, CPU tests, preflight, mechanical audit, grading |
| [one-waiter/config/](one-waiter/config) | Frozen plan, published cohort and the source lock the runs were launched against |
| [one-waiter/inputs/](one-waiter/inputs) | Pinned question slices and the dataset manifest |
| [one-waiter/logs/](one-waiter/logs) | Session, monitor, watchdog and scoring logs, plus the report's number dump |
| [one-waiter/analysis/](one-waiter/analysis) | [Expected versus achieved answers](one-waiter/analysis/coverage-audit.json) and [machine-readable verdicts](one-waiter/analysis/verdicts.json) |
| [one-waiter/results/](one-waiter/results) | One directory per GPU run; [results/README.md](one-waiter/results/README.md) explains each file and why failed attempts are kept |

Quick reproduction (CPU only, no GPU):

```bash
cd week5/builder/one-waiter/code
module load python/3.11.9
python3 -m unittest discover -s . -p 'test_*.py'   # policy/controller tests
python3 preflight.py --local                       # locks, plan keys, cohort, inputs, traces
python3 verdicts.py                                # premise / fix verdicts per workload
python3 summarize_results.py                       # compact per-run tables
python3 coverage_audit.py                          # expected vs achieved answers
```

Scoring one run needs the grading environment (Math-Verify), not the serving one:

```bash
<ENV>/analysis-venv/bin/python -B \
    week5/builder/one-waiter/code/analyze5.py --root week5/builder/one-waiter/results/job-<id>-<condition>
```

GPU work runs one condition per H100 job with 64 GB host memory. The sbatch script finds the
checkout from its own path, so it can be submitted from anywhere:

```bash
CONDITION=gate CAP_SECONDS=800 sbatch --export=ALL \
    week5/builder/one-waiter/code/run_condition.sbatch
```

## Paths and environment

No path in this workstream is tied to a particular machine, user or account. Every script resolves
the checkout from its own location:

| Variable | Meaning | Default |
| --- | --- | --- |
| `<REPO>` | the repository root, derived from the script's own path | — |
| `<ENV>` (`LARB_W5_ENV_ROOT`) | the serving environment: `venv/`, `hf-cache/`, `model/Qwen3-4B/` | `<REPO>/.w5-env` |
| `LARB_W5_ANALYSIS_PYTHON` | the grading interpreter (`analyze5.py`) | `<ENV>/analysis-venv/bin/python` |

`<ENV>` is not tracked, so set `LARB_W5_ENV_ROOT` to wherever you provisioned the environment;
[REPORT.md §8.3](REPORT.md) lists what has to be in it.

Week 4 evidence is read-only here; the Week 3/4 controller files are imported, never edited, and
[one-waiter/code/test_policy.py](one-waiter/code/test_policy.py) asserts their SHA-256 against the
Week 4 lock.

