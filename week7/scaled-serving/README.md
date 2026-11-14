# Week 7 scaled serving

**Start here:** [PLAN.md](PLAN.md) is the execution plan. This README orients you and indexes the
background binder in [binder/](binder/); the plan's detailed chapters live in [plan/](plan/).

> **P0 complete; P1 GPU gates complete.** The rig, datasets and CPU code live in `code/`,
> `configs/`, `data/` and `artifacts/`. The P1 gate job is written up in
> [reports/P1-REPORT.md](reports/P1-REPORT.md): the rig passes (bridge, 32-row mechanics, contract,
> throughput), but the 2025-2026 main pool fails the slope preview, so **P2 is withheld pending a
> pool change**. P0 status: [reports/P0-REPORT.md](reports/P0-REPORT.md).

**The [binder](binder/) is not itself a plan.** It is the information set the plan was written from:
what our experiments actually are, what they have shown, what the nearest published work does, which
datasets could carry a bigger study, which knobs and experiments look promising, and what
engineering work stands between us and a rig that produces useful data quickly.

No GPU work was run to produce this folder. The experimental numbers are taken from already-saved
results in this repository and cross-checked against the evidence files named in
[binder/02-evidence.md](binder/02-evidence.md); the published-work numbers in
[binder/03-related-work.md](binder/03-related-work.md) were re-read from the papers themselves in
November 2026.

## How this folder is organised

| Path | What it is |
|---|---|
| [PLAN.md](PLAN.md) | The execution plan: hypothesis, realism-first main path, decision rules, sign-off. |
| [binder/](binder/) | The information set the plan was written from: files 01-06. |
| [plan/](plan/) | The plan's detailed chapters: rig design, experiment design, main path, risks, open decisions, feasibility and artifacts: files 07-13. |
| [code/](code/README.md) | CPU-safe package, tests, tools and sbatch drafts. |
| [configs/](configs/) | Frozen protocol, dataset, gate and main-run configurations. |
| [data/](data/) | Raw and normalized dataset snapshots with manifests. |
| [artifacts/](artifacts/) | Frozen cohort, traces and hash manifest. |
| [reports/](reports/) | Consolidated P0 status and the P1 GPU gate report. |
| [logs/](logs/), [results/](results/) | Isolated local outputs; logs and large run records are gitignored. |
| [experiment-matrix.csv](experiment-matrix.csv) | Arm-by-condition matrix for P1-P4. |
| [feasibility.py](feasibility.py) | CPU-only reproduction of the arithmetic in [plan/12-feasibility-notes.md](plan/12-feasibility-notes.md). |

## The question these documents serve

The project's working hypothesis, unchanged:

> Under bursty or sustained load, shortening the thinking budget of requests already running when
the queue builds delivers more correct-by-deadline answers than (a) choosing the budget once at
admission or (b) a fixed short budget, while keeping eventual accuracy within about 3 percentage
points of full thinking.

The 3-point figure is a working tolerance, not a law. The rest of the sentence is the actual claim.

## The problem to solve first

Our current rig produces roughly **25-110 measured responses per GPU-hour, and 30-60 for the AIME
workloads we care about**. That is enough to see a 10-20 point effect on a good day and nowhere near
enough to resolve the 2-4 answer differences we keep arguing about, which is why six weeks of work
still end with "tied" or "probably not noise".
The rig is also deliberately minimal (two concurrent requests, a 4-billion-parameter model, a
2,048-token answer allowance), so some of what it measures is an artefact of the rig rather than a
property of the idea.

The plan this binder feeds should aim at something like **500-2,000 measured responses per arm per
GPU-day**, on a workload whose accuracy genuinely moves with the thinking budget, at a concurrency
where the queue is real.

## What is in the binder

| Binder file | Question it answers |
|---|---|
| [01-current-rig.md](binder/01-current-rig.md) | What have we built, what is pinned, and which choices are quietly shaping every result? |
| [02-evidence.md](binder/02-evidence.md) | What do the results actually support, and where does the central hypothesis stand? |
| [03-related-work.md](binder/03-related-work.md) | How do the closest papers evaluate, on what data and hardware, and what should we copy, avoid or qualify? |
| [04-datasets.md](binder/04-datasets.md) | Which datasets could give us a steep accuracy-versus-budget slope at single-GPU scale? |
| [05-ideas.md](binder/05-ideas.md) | Unordered list of concrete things to try, each with cost and risk. |
| [06-engineering-gaps.md](binder/06-engineering-gaps.md) | What breaks or gets harder when we scale, and what must be measured first. |

The plan's own chapters, in the order [PLAN.md](PLAN.md) recommends reading them, are
[plan/09-main-path.md](plan/09-main-path.md), [plan/07-rig-design.md](plan/07-rig-design.md),
[plan/08-experiment-design.md](plan/08-experiment-design.md),
[plan/12-feasibility-notes.md](plan/12-feasibility-notes.md),
[plan/10-risk-register.md](plan/10-risk-register.md),
[plan/11-open-questions.md](plan/11-open-questions.md) and
[plan/13-artifact-and-reproduction.md](plan/13-artifact-and-reproduction.md).

## Questions the plan must answer

These are deliberately left open here:

1. What is the target statistical resolution, and therefore the minimum number of independent
   questions, seeds and repetitions?
2. Which dataset pool, and does the current pool still serve as a bridge for comparability?
3. What concurrency, answer allowance, and model size give the best data per GPU-hour without
   making the measurement meaningless?
4. What replaces "a request waited" as the pressure definition when many requests can wait?
5. How are deadlines set so that the on-time metric is sensitive rather than decorative?
6. Does the controller stay a patched-scheduler hack, or move to an interface that survives an
   engine upgrade?
7. Which two or three policies form the core comparison, and what is explicitly out of scope?
8. What is the stopping rule that prevents another six weeks of underpowered one-off runs?

## House rules carried forward

Freeze sources and traces before measuring; keep every failing, capped and late outcome in the
denominator; never choose a threshold or a dataset after seeing the score; report per-question
paired changes, not just totals; and treat a tie as a result worth publishing.
