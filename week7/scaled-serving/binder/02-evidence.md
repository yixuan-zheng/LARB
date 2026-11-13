# 2. What the evidence actually supports

Everything here is a saved measurement. The rig and its assumptions are in
[01-current-rig.md](01-current-rig.md); this file is the distilled version a planner can trust
without reading the six weekly packages.

## 2.1 The raw material: does more thinking buy better answers?

This is the premise the whole project stands on, and it is strongly dataset-dependent.

| Pool | Budgets tested | Accuracy | Source |
|---|---|---|---|
| AIME 2025 (30 questions x 2 seeds) | 2k / 4k / 8k / 16k thinking | 30.0% / 36.7% / 45.0% / 51.7% | 60 responses per budget |
| AIME 2024 (30 questions x 2 seeds) | 4k vs 8k, same prefix | 30% / 45% | 40 branched instances |
| MATH-500, first 100 | 256 / 512 / 1k / 2k / full (16k safety) | 87% / 87% / 89% / 90% / 95% | 100 responses per budget |
| MATH-500, 21-question slices | 2k vs 4k vs unrestricted | identical across all policies | 141 scored answers |

Reading these together:

- **On AIME the slope is real and steep.** Going from 4k to 8k is worth about 8 points (2025) or 15
  points (2024). On the 2025 screen, 2k to 8k is worth 15 points at 2.5 times the mean time, and 2k to
  16k is worth 22 points at 3.6 times. This is the only pool in the project where budget choice
  visibly changes the answer.
- **On MATH-500 the pool is near its ceiling.** Full thinking gets 95%, the best short budget gets
  90%, and on the 21-question slices used for the serving work, extra thinking bought **exactly zero**
  additional correct answers across every policy. A dataset like that cannot show a scheduling benefit.
- **Many requests are insensitive by nature.** In the one-at-a-time workload, three of six questions
  closed their own thinking below 2,048 tokens and three ran to 2.2-4.2k; all six were answered
  correctly under every policy. A budget only matters for the subset that is still thinking.

Two useful implications. First, dataset choice is not a detail; it decides whether the hypothesis is
testable at all. Second, on AIME the accuracy-versus-budget curve has never been sampled between 4k
and 8k, which is where a cheap policy fix might live.

## 2.2 The serving results, study by study

"Correct on time" counts only correct answers that finished normally inside their deadline. Capped
answers are wrong. Scales are small enough that a 2-3 answer difference is not a result.

| Study | Scale | Arms and correct-on-time | Reading |
|---|---|---|---|
| week 3 burst pilot | 12 questions, 1 trace | full 4, arrival-only 3, live 6 | first positive signal, n=12 |
| week 4 development | 12 questions x 2 blocks = 24 | full 7, arrival 8, admission 8, live 12 | +4 over admission, +2 in each block |
| week 4 held-out | 24 questions, 6 jobs, 96 pressure responses per policy | admission 39, live 51 | +12.5 points, eventual accuracy equal, one quality loss |
| week 4 fixed-budget controls | 12 questions x 2 blocks | late burst: fixed2k 9, fixed4k 5, admission 3, live 9; sustained: fixed2k 23, fixed4k 8, admission 9, live 21 | live beats admission, but **fixed-2k wins sustained and ties burst** with fewer tokens |
| week 5 one-waiter | 6 questions per workload | constant pressure: fixed2k 12, fixed4k 11, live 12, live_one 12; one-at-a-time: everything 12 | no quality differences at all on this pool |
| week 5 queue-pressure pilot | 12 questions x 3 conditions = 24 | fixed4k 6, fixed8k 7, live 7 | tie with 8k at 15.7% fewer tokens and 26.7% lower latency |
| week 6 two blocks | 12 questions x 2 seeds x 2 blocks = 40 | fixed4k 8, fixed8k 12, arrival 11, live 11 | tie on the primary count; overall correct 13 vs 16 |
| week 6 engine-entry | 12 questions x 2 blocks = 24 | arrival 6, entry 7, live 7 | moving the decision earlier keeps the timing benefit, not the quality |

## 2.3 What is established, and with what confidence

**Solid.** Cuts reliably reduce work. Live used 15-17% fewer output tokens and 27-48% lower latency
than the 8k or arrival-only alternatives in every study where it fired, and there is no observed case
where the mechanism made a condition slower or more expensive. Cuts also release capacity in the same
scheduler step that a request completes, so the mechanism is not defeated by slow slot recycling.

**Solid but unwelcome.** A fixed short budget is a strong competitor. Across the six studies that had
a short-budget arm, it ties live twice and beats it once (both ties and the loss are on MATH-500-style
pools, and the loss is the sustained-pressure condition); live wins the other three, all against a
fixed 4k budget. Any new claim has to beat fixed-short, not just admission.

**Directional, not solid.** Live almost always beats admission-only (five of six studies; the sixth
is a tie). The mechanism is real: queued requests that would have missed their deadline finish on
time. But the size of that gain has never been reproduced twice on the same cohort with enough data to
separate it from noise.

**Not established.** Live beating a fixed long budget on the primary metric: two wins (week 3 burst
against unrestricted thinking, week 4 development against full thinking), one tie (week 5 pilot against
fixed 8k), one loss (week 6 two blocks against fixed 8k).

**Actively doubtful.** "Keeping eventual accuracy within 3 points of full thinking." In the two
largest recent samples the gap was larger: week 6 live 13/40 correct against 17/40 for fixed-8k (a
10-point gap) and 16/40 for arrival-only (7.5 points); week 4's pressure campaign was 22/24 against
23/24. Some of that is noise and some is real quality loss from early cuts, and today's data cannot
tell them apart.

## 2.4 Where the central hypothesis stands

> *Under bursty or sustained load, shortening the budget of running requests delivers more
> correct-by-deadline answers than (a) choosing at admission or (b) a fixed short budget, while
> keeping eventual accuracy within about 3 points of full thinking.*

| Clause | Verdict | Evidence |
|---|---|---|
| Beats admission-only | **Probably yes, magnitude unknown** | 5 studies positive, 1 tie; gains ranged from +2 to +12.5 points |
| Beats fixed short | **No clear win** | 3 wins, 2 ties, 1 loss; the ties and the loss are on MATH-500-style pools |
| Accuracy within ~3 points of full | **Not met in the largest samples** | 4-10 point gaps in weeks 4 and 6; no measurable gap in the small week 3 and week 5 samples |

That is a fair summary of an unproven but not disproven idea. It is also a summary written on top of
a rig that cannot resolve a 3-point difference, which is the point of the next plan.

## 2.5 Why the on-time metric has been sleepy

Where the deadline sits decides how much the metric can show. In weeks 5-6 the deadline was about
236 s against mean latencies of 140-200 s, so the pooled two-block comparison produced only 3-9
deadline misses out of 40 per policy, and the on-time counts landed within 4 answers of each other.
In week 4 the deadlines were 95-125 s against medians of 50-170 s, and the same kind of policy
comparison spread from 3/24 to 23/24. That spread is mostly a property of the deadline, not proof of a
stronger mechanism, and no one has yet chosen the deadline with that in mind.

## 2.6 What would change our mind

- If, at several hundred responses per arm, live's advantage over fixed-short disappears, the
  hypothesis is false as written and the project should pivot to a different lever or a different model.
- If the accuracy gap against full thinking is stable at 5-10 points rather than 3, the mechanism
  needs changing (cut later, cut less, cut only some requests) before any serving claim is made.
- If cuts help only when the request has not yet found its route, then the useful control variable is
  progress, not queue length, and the traffic-only framing is the wrong abstraction.
- If a scaled rig shows the effect shrinking as concurrency rises, then the current rig was an
  artifact and the single-slot intuition does not survive a real batch.

## 2.7 What these results cannot be used to claim

Not that live is better than a well-chosen fixed budget; not that its accuracy cost is bounded; not
that the effect generalises beyond 12-30 AIME/MATH-500 questions; not that the GPU was well used;
not that any individual cut caused any individual answer change, since matched seeds do not produce
matched trajectories; and not that the answer-cap failures are distributed like real errors.

## 2.8 Where these numbers come from

Every figure above is copied from a saved result, not recomputed here. The files to check:

| Claim | Source in this repository |
|---|---|
| Budget-versus-accuracy curves | `week5/pressure-followup/README.md` and `RESULTS.md` (AIME 2025 screen); `week3/larb/STAGE3-REPORT.md` (MATH-500 sweep); `week6/research-handoff/results.json` (AIME 2024 shared prefix) |
| Week 3 serving result | `week3/larb/BURST-POLICY-REPORT.md`, `week3/larb/README.md` |
| Week 4 development and held-out results | `week4/step1/controlled-comparison/REPORT.md`, `week4/HANDOFF.md`, `week4/reserved-validation/REPORT.md` |
| Week 4 fixed-budget controls | `week4/baseline-controls/REPORT.md` |
| Week 5 one-waiter result | `week5/builder/REPORT.md` |
| Week 5 queue-pressure pilot | `week5/pressure-followup/STAGE3-REPORT.md` |
| Week 6 two-block comparison, caps, timing | `week6/admission-timing-audit/FOLLOWUP-RESULTS.md`, `evidence/audit-summary.json`, `evidence/phase-summary.json` |
| Week 6 engine-entry result | `week6/research-handoff/results.json` (`engine_entry`) |
| Cut, release and prefix-divergence diagnostics | `week6/admission-timing-audit/REPORT.md`, `evidence/release-events.json`, `evidence/budget-paths.json` |
