# Starting points for next week

Week 4 leaves a working system and a concrete research question: when does revising reasoning during execution deliver useful quality/deadline/compute value beyond a well-chosen static budget? Similar high-level ideas do not rule out a contribution. The mechanism, resulting capability and strength of evidence determine its significance.

Start with the [fixed-budget result](baseline-controls/REPORT.md), [offline diagnosis](baseline-controls/diagnosis/REPORT.md), and [literature evidence audit](literature-audit/REPORT.md). The [handoff](HANDOFF.md) links the broader history. The following are options, not a requirement to follow every route.

| Option | Why it is worth considering | Risks / what it would establish | Our assessment |
| --- | --- | --- | --- |
| One-waiter pressure ablation, with a quality-versus-budget study | Directly tests the observed two-waiter blind spot while asking whether longer reasoning buys useful quality | Earlier irreversible cuts may harm quality; beating old live alone does not demonstrate value over static budgets | Recommended first bounded study; small change, discriminating evidence |
| Broader static-budget characterization | Tests whether an intermediate static setting explains apparent adaptive gains; maps quality/cost opportunity | Sweeps can overfit; choose settings on development data and assess on separate traces/cohorts | Keep 2,048/4,096 immediately; expand a modest sweep before broader static-superiority claims |
| Deadline/cue-and-answer reserve guard | Could address own-deadline misses even with little queueing | Needs deadline transport and service/answer-time estimates; stopping thinking does not finish the answer instantly | Useful if the next traces show this as a repeatable limitation; isolate from the threshold change |
| Persistence before committing to a cut | Could avoid cuts from brief queue spikes | Waiting longer can recreate late cuts; budgets cannot be restored after finalization | Consider only if transient pressure is shown to cause avoidable losses |
| Select which active request to shorten | Could trade marginal quality cost against useful capacity release for others | Harder to estimate benefit; sampled alternate answers and service times are unknown; requires stronger controls | Higher development effort, promising if simple triggers leave systematic misallocation |
| Progress/confidence signals | May distinguish requests that benefit from continuation | Probe/replay/calibration costs and runtime semantics can consume the gain | Retain as an option; justify the signal through observed need and full cost accounting |
| Paper-based LASER adaptation | Tests a concrete alternative to nonprobing control | Native fork/rollback unavailable through our inspected public API; replay changes cost, RNG and queue order; paper defaults mismatch two slots | Feasibility work is saved; defer integration until its scientific question justifies the engineering |
| Stronger scheduling control or prior-system comparison | Tests whether reasoning-control benefit survives better queue service | Mixing scheduler changes with budget changes obscures attribution; prior systems target different workloads | Later robustness/comparison stage, with separate matched ablations |
| Another application-motivated model/task distribution | Could reveal useful reasoning/latency tradeoffs absent from the current cohort | Selecting tasks after observing favorable outcomes would weaken the study | Legitimate if chosen for deployment relevance before outcomes; current negative findings remain in the record |

## A concrete first experiment to refine, not launch automatically

The existing proposal compares fixed-2,048, fixed-4,096, unchanged live (two waiters) and a one-waiter candidate. Keep long/short budgets, cue, answer cap, stock scheduling and runtime matched. The candidate is not implemented. Test the trigger repair and the opportunity for adaptivity together:

- Isolated requests measure useful quality versus reasoning budget without queue interference. Report per-request quality/latency/tokens; policy-dependent draining is not matched wall-clock goodput.
- Sustained pressure tests whether the candidate closes the efficiency gap to fixed-short.
- Exogenous slack → burst → recovery tests behavior as conditions change. Actual queue occupancy matters more than a nominal “low-load” label.

The proposal uses 24 additional questions hash-selected from the exposed 0–99 pool, excluding the current comparison/calibration/gate cohort, two predefined blocks/seeds and three conditions: 576 measured outcomes. Cohort selection must ignore accuracy, observed length and whether a question favors long reasoning. Rotate assignments and publish policy order. Exact manifests and a realistic compute estimate/cap remain to be frozen before execution. Budget for startup, storage and long isolated reasoning; stage complete comparisons rather than repeatedly allocating tiny smoke tests. Do not continue or rerun based on favorable quality outcomes.

The earlier held-out 24 questions are now exposed; they cannot become an untouched validation set for a revision. Recorded project exposure is 124 unique indices. The other 376 remain provisionally unused, subject to a fresh exposure audit; external use and pretraining are unknown. Preserve a genuinely unused confirmation cohort for any candidate chosen through development.

## How we would interpret the next result

A meaningful result can be a better operating tradeoff rather than a win on every metric. Report correct final answers before deadline, eventual correctness, mean/tail client latency, queue delay and full computation/overhead, including calibration and discarded auxiliary work. Keep condition-wise and paired losses visible. Fix application weights and quality tolerances before scoring; do not choose traffic weights afterward.

If one-waiter improves on old live but still loses to fixed-short without compensating value, it is a useful mechanism result, not a demonstrated adaptive advantage. If longer reasoning gives reproducible useful quality under slack while congestion behavior approaches fixed-short, that supports a stronger adaptive-control claim and an independent confirmation study. If no useful long-budget benefit appears, the conclusion applies to the tested model/workload; it does not settle all adaptive computation. Additional savings below 2,048 or heterogeneous deadline requirements are other possible opportunities, to be motivated and tested rather than assumed.

A contribution need not invent an unprecedented primitive. A lightweight mechanism with substantial practical improvement, a sound concurrent implementation and cost study, or a generalizable characterization can each be valuable. The literature audit supplies hypotheses and comparison standards; it does not dictate our architecture or require reproducing every system before progressing.

## Practical handoff

There are no active campaign jobs and no new experiments queued. All existing comparison outcomes are collected and graded. Work can begin with CPU implementation of the chosen isolated change once the next lead chooses a plan. The existing frozen controller and run snapshots remain reference evidence. New experiment folders can hold their own configuration, results and explanation, with a short update to the Week 4/next-week handoff identifying what changed and why. Personal cluster login and workspace paths remain local configuration.
