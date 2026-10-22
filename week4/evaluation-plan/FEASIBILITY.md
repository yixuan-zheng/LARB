# Feasibility of deadline-aware cross-request intervention

This is a design investigation using the current source and saved development traces. It does not change the controller or use reserved questions. [signal-audit.json](signal-audit.json) records the source hashes and measured observations.

## What the current implementation can and cannot observe

`w4_policy.py` uses waiting-count pressure and a fixed long-to-short reduction. `w4_adapter.py` identifies requests, attaches admission decisions, and records generation progress. The serving path preserves the same request and lets the answer complete after forcing the transition. The controller currently receives neither per-request deadlines nor a model of remaining work; deadlines are used by the offline replay scorer.

| Quantity | Evidence or missing interface | Use in a possible controller |
| --- | --- | --- |
| Waiting/active membership and admission | Existing scheduler snapshots and metadata | Identify affected requests; preserve current scheduling order |
| Generated progress, budget, phase | Existing worker state/events | Avoid answer-phase changes; estimate time to a candidate cut |
| Time to actual capacity release | Service completion after cue/close events, same-host clock | Include transition and answer reserve, not just thinking savings |
| Per-request deadline/slack | Currently only in replay/scoring context | Needs explicit online transport with clock-domain checks |
| Natural remaining computation | Known only after a request completes | Needs an exposed-data estimate; current budget is not a prediction |
| Queued service time | Offline observations, not a ready online predictor | Needs uncertainty-aware service estimates including answer time |
| Quality loss from a cut | Only sampled paired outcomes, with batching variation | Measured offline; no calibrated online risk guarantee |
| Counterfactual queue outcome | Not directly observed | Forecast for action selection; real paired inference for validation |

For the two binding development pivots, cue-start to final completion was **9.713s and 9.658s**. Even after thinking closure was detected, about **9.46s and 9.42s** remained. These are observations for the same exposed question twice, not a universal answer-reserve estimate. A revision issued earlier also waits until the reduced budget is reached; neither the decision timestamp nor the first forced token is slot release.

Two pivots and two unique rescued questions are too little to fit or validate a useful predictor. The traces show a possible opportunity and usable instrumentation. They do not establish forecast accuracy, action optimality, or causal counterfactual durations for other cuts.

## Two small mechanisms to consider after planning

**1. Deadline guard.** Keep the existing pressure trigger but require evidence that a waiting request can benefit from earlier capacity release. Use a conservative exposed-data estimate of time to the existing 2,048-token cut plus cue/answer completion, and the earliest waiting deadline with a service reserve. Compare this with current LARB. It tests whether slack information helps without solving a larger optimization problem.

**2. Downstream-benefit selection.** Under the same pressure and safety guards, evaluate no action and one cut of each eligible active request to the existing short budget. Forecast queued completion under the unchanged FIFO/two-slot service model, including the active request's answer reserve and the other slot. Select a single cut only if its predicted increase in deadline-feasible completions exceeds the no-action forecast under the estimate's uncertainty. This first version chooses whom to cut; variable cut sizes are a later extension.

Both proposals use observed serving state, not final answers, hidden future arrivals, or test labels. A cut remains monotonic, never reopens thinking, completes the cue, and preserves answer allowance. Missing/stale estimates lead to a recorded no-action decision. Accuracy costs are still measured: a predicted count of feasible completions is not a predicted count of correct answers. The forecast cannot be advertised as optimizing expected correct goodput without a justified quality model.

Before writing either controller, exposed-only data can provide conditional remaining-work and cue/answer-duration estimates. Leave-question-out checks should hold out all repeats of a question together. A coarse interval or empirical quantile is more defensible initially than a precise learned forecast. If uncertainty makes action rankings indistinguishable, the sensible next step may be a small diagnostic data collection, with a new plan, rather than a larger controller.

## A discriminating development experiment

Use exposed questions only, with a separately frozen plan and actual inference rather than scored replay of hypothetical cuts. Keep prompts, arrival times, seeds, active-request deadlines, initial budgets, and engine settings fixed. Change only waiting-request deadline assignments before replay:

- **Recoverable:** an earlier slot release could plausibly rescue a waiting final answer.
- **Unsalvageable:** the tight deadline is too near even after paying the cue/answer and queued service reserves.
- **Loose:** waiting work can plausibly finish without a cut.

These pairs test information beyond active-request slack and queue length. A stronger second pair keeps the minimum waiting slack fixed while changing how many other waiting requests are plausibly recoverable; that separates a simple minimum-slack guard from downstream-benefit counting. The deadline assignments are chosen on development data and frozen before comparing policies, including unfavorable cases.

Controls would include current LARB, the simple deadline guard, downstream selection, no-cut admission, and a feasible closest-method adaptation from 6A. A nonpreemptive EDF waiting-order control can separate reordering from shortening. If EDF changes scheduling, all affected comparisons use that explicitly identified condition. The action selector itself initially keeps stock scheduling.

Evidence would include chosen action/no action, predicted release-time interval and affected requests, actual release, admission sequence, final receipt, eventual correctness, binding/nonbinding cuts, and overhead. Removing answer reserve or downstream counting provides targeted ablations. Controller CPU time and any prediction/probing work belong in the latency and cost record.

## Decision before committing more resources

A useful implementation case needs: a credible prior-work distinction; at least some robustly distinguishable action opportunities on exposed data; a reproducible, cheap estimate; and a comparison where a simple deadline guard could win. CPU decision overhead can be measured against a predeclared 5ms P95 target and a 1% end-to-end overhead target in a later GPU plan, rather than assumed negligible.

If these checks do not hold, retaining current LARB as a characterized load heuristic is a valid outcome. For now the recommendation is to keep the 5A candidate frozen, prepare the 5B input/replay support, and resolve the 6B probing contract and missing deadline interface before a new controller. No reserved question has been generated, and no GPU resource was used for this investigation.
