# Controlled admission/live comparison

Job **6440653** completed after real 1C job **6440402** passed all 176 checks.
The [final report](REPORT.md) records live **12/24** correct-on-time outcomes
versus admission **8/24**, over two replays of 12 unique development problems.
Read the [predeclared plan](PLAN.md), [configuration](spec.json), and
[candidate gate](gate.json). All policies share one engine/allocation and one
frozen, open-loop trace. There are 12 unique development questions and two
reverse-order blocks, not 24 independent accuracy examples.

CPU preparation: six metric tests, the real calibration/trace rule, and pinned
grader regressions passed. Serving dependencies are unchanged; local analysis
packages live separately in ignored `week4/.analysis-deps/`.

Both jobs are collected, so reproducing the saved analysis needs no new GPU allocation.
The archived scheduler log is losslessly compressed for Git, with raw/compressed
hashes in `results/job-6440653/storage-manifest.json`. Plaintext remains locally
and on PACE. Materialize it before using the original analysis code:

```bash
python3 -B week4/step1/controlled-comparison/checks/pack_events.py \
  --root week4/step1/controlled-comparison/results/job-6440653 --unpack
```

Saved results are in `results/job-6440653/`.
The package pins are in `week3/larb/stage3/requirements-analysis.txt`. From the
repository root, with those analysis dependencies installed separately:

```bash
python -B \
  week4/step1/controlled-comparison/analyze.py \
  --root week4/step1/controlled-comparison/results/job-6440653
```

The scorer requires a complete fixed workload, validates sources/inputs,
calibration, trace freeze, queue rules, admission metadata, overlap, live changes,
cue tokens, caps, identity and sampled KV continuity, then applies the existing
Math-Verify 0.9.0 grader to final answers. It retains failures and parser issues.
Review `analysis/review-queue.json` and paired admission/live outcomes before
writing the conclusion. No policy tuning or favorable-result retries are planned.

To regenerate the paired cases and presentation figure after scoring:

```bash
python3 -B week4/step1/controlled-comparison/checks/explain_cases.py \
  --root week4/step1/controlled-comparison/results/job-6440653
MPLCONFIGDIR="$PWD/week4/.analysis-deps/matplotlib-cache" \
  XDG_CACHE_HOME="$PWD/week4/.analysis-deps/cache" \
  python -B week4/step1/controlled-comparison/checks/plot_results.py \
  --root week4/step1/controlled-comparison/results/job-6440653
```

## Notes for whoever continues

The [handoff](../../HANDOFF.md) summarizes the current state and next research question. The [progress notes](../README.md#sharing-progress) suggest what is useful to leave for the next person: a short explanation of changes, verification results, output paths, open questions, and any active jobs. This README holds commands; the report explains the findings.
