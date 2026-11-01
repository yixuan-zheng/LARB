# Week 5 — choosing the path (A lane: builder)

Week 5 asks one question that decides the semester: does thinking past 2,048 tokens ever buy a
better answer on this task, and if it does, can the server recover fixed-2,048 congestion
efficiency by cutting at the **first** waiting request instead of the second? The plan is in
[`../Week 5 Plan.md`](../Week%205%20Plan.md); this folder holds the A-lane work (implementation,
mechanics gate, GPU runs, collection and scoring).

**Read the [report](REPORT.md)** for the measured result and the three verdicts (premise, fix,
targeting ingredients); [one-waiter/PLAN.md](one-waiter/PLAN.md) holds the frozen design and the
sessions it was run in. Everything is reproducible from the commands below without touching a GPU.

| Path | What it is |
| --- | --- |
| [REPORT.md](REPORT.md) | What was built, the gate, the three workloads, verdicts, limits, engineering record |
| [one-waiter/PLAN.md](one-waiter/PLAN.md) | Frozen design, cohorts and their per-condition slices, traces, analysis rules, session scale |
| [one-waiter/](one-waiter) | Policy module, serving adapter, runner, CPU tests, preflight, mechanical audit, grading, results |
| [one-waiter/results/README.md](one-waiter/results/README.md) | What each file in a run directory is, and why failed attempts are kept |
| [one-waiter/coverage-audit.json](one-waiter/coverage-audit.json) | Expected versus achieved answers per condition |
| [one-waiter/verdicts.json](one-waiter/verdicts.json) | Machine-readable premise/fix verdicts computed from the scored rows |

Quick reproduction (CPU only, no GPU):

```bash
cd week5/one-waiter
module load python/3.11.9
python3 -m unittest discover -s . -p 'test_*.py'   # policy/controller tests
python3 preflight.py --local                       # locks, plan keys, cohort, inputs, traces
python3 verdicts.py                                # premise / fix verdicts per workload
python3 summarize_results.py                       # compact per-run tables
python3 coverage_audit.py                          # expected vs achieved answers
```

Scoring one run needs the grading environment (Math-Verify), not the serving one:

```bash
/home/hice1/jwang3221/scratch/LARB-week5-env/analysis-venv/bin/python -B \
    week5/one-waiter/analyze5.py --root week5/one-waiter/results/job-<id>-<condition>
```

GPU work runs one condition per H100 job with 64 GB host memory:

```bash
cd /home/hice1/jwang3221/scratch/LARB
CONDITION=gate CAP_SECONDS=800 sbatch --export=ALL week5/one-waiter/run_condition.sbatch
```

Week 4 evidence is read-only here; the Week 3/4 controller files are imported, never edited, and
[one-waiter/test_policy.py](one-waiter/test_policy.py) asserts their SHA-256 against the Week 4
lock.

