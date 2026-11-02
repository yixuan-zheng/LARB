# C4: path memo — targeted shortening

**Recommendation: take the backup path (measurement study).** The targeting check does not block the ideal path: a deadline-aware rule decides very differently from cut-whenever-full. But the other two verdicts fail, and on this model, task and deadline scale there is almost nothing for a smarter cut to win. Keep targeting as a written follow-up, conditioned on a harder workload.

## The three verdicts (plan: ideal path only if all three hold)

| Verdict | Result | Source |
| --- | --- | --- |
| Premise: extra thinking past 2,048 buys correct answers | **No on the 6 Week 5 questions**; weakly yes in Week 3 (below) | lane A report, `week5/REPORT.md` §5.1 (`builder` branch) |
| One-waiter still leaves a quality gap vs fixed-2,048 | **No**: 12/12 vs 12/12 on time under constant pressure, median 47.7 vs 46.1 s | same, §5.2 |
| Targeting discriminates | **Yes**: disagrees at 91% of cuttable decision points | this folder, [results/](results/) |

## What the targeting check found (C3)

The shadow rule cuts at most one running request, and only if that gets one of the next two waiters in by its deadline. Replayed on all 8 Week 4 runs (480 requests; state rebuild reproduces all 46 recorded live cuts within 0.5 s, and all 480 on-time flags):

- It disagrees with cut-whenever-full at **2,607 of 2,856** decision points where something could be cut (89–94% under ±25% on every estimate), and in **all 38** full-server episodes where cut-whenever-full cuts: never cuts in 22, cuts later in 16.
- The disagreement is about **whether and when** to cut, not **which** request: with two slots, cut-whenever-full already cuts everything eligible, so the rule can only cut less. Cutting one of two instead of both is 9% of points.
- **"Will miss" predictions are reliable** (61 of 61 waiters at first call, in phases that never cut live). **"Will make it" predictions are not**: 8 of 19 waiters missed. Median remaining-thinking and service estimates are too optimistic for the long tail.
- **Half of the "doomed" states have a head waiter already past its deadline, and 59% have 3+ waiters.** Not cutting there spares the running request but delays everyone further back. That knock-on effect is exactly why fixed-2,048 beat live under sustained pressure in Week 4, so these abstentions could be harmful.

So the rule discriminates, but nothing here shows its choices are *better*.

## What gain is plausible

The only thing targeting can buy over fixed-2,048 / one-waiter is letting a request think long when (a) long thinking would fix its answer and (b) nobody's deadline pays for it.

- (a) is rare. Week 3 Stage 3 (100 questions, one sample each): full thinking was right and 2,048 wrong on **6 questions** (18, 36, 43, 64, 71, 94), the reverse on 1. The 95% interval on that 5 pp gap is −10 to 0 pp.
- (a) and on time is rarer still. Those 6 answers took **125–363 s** in Stage 3 (5,055–15,283 thinking tokens), against relative deadlines of 95–149 s in Weeks 4–5. At most one (question 36, 125 s) is near any deadline we have used.

**Ceiling: about 0–1 extra correct-on-time answer per 100 questions**, and up to ~5 pp of eventual accuracy if late answers counted. Lane A's runs saw neither (136/141 correct; the only wrong question was wrong under every policy).

## What the ideal path would need

1. A workload where 2,048 tokens actually costs correct answers that can still arrive on time: harder questions, a smaller model, or longer deadlines with real traffic, chosen **before** looking at outcomes.
2. A rule that sees the whole queue, not the next two waiters, so a doomed head waiter doesn't stall everyone behind it.
3. Better "will make it" estimates: use a distribution or upper percentile of remaining thinking, not the median.
4. A live implementation: deadlines passed from client to controller (`extra_args`), then a matched GPU comparison against fixed-2,048 and one-waiter.

## Risks

- Targeting's cost side is real (delayed cuts lengthen the queue) while its benefit is close to zero on this pool, so a live test could easily lose to fixed-2,048.
- Estimates are in-sample (built from the same records they are tested on) and use one service time for every request.
- 12–24 repeated questions per run; Week 4 cohorts are exposed.

## What evidence would confirm it

On a pre-registered harder cohort: (1) a one-at-a-time run where longer budgets fix answers in **both** blocks and finish inside the deadline; then (2) a shadow replay where the rule's "will make it" calls are right ≥90% of the time; then (3) a live run where targeting beats fixed-2,048 and one-waiter on correct-on-time with no workload losing more than one answer. Any one failing sends it back to the backup.
