# Week 5 Plan — Choosing the Path

**Mon 26 Oct – Mon 2 Nov 2026** · Three people · Checkpoint Thursday 29 Oct, morning

## Purpose

Week 4 produced a working mechanism and an awkward result. We can shorten a request's thinking mid-answer, but a plain fixed allowance of 2,048 tokens matched or beat our adaptive policy. Our read of the closest papers also showed that "adapt under load" is already claimed; the one angle that still looks unclaimed is choosing *which* request to shorten.

That leaves two credible ways to finish the semester. This week decides between them.

**Backup — a measurement study.** "On a real two-slot server, here is when shortening thinking helps and when the simplest fixed allowance is just as good or better." A careful characterization, not a new idea, but a real result that stands even if every hypothesis fails.

**Ideal — targeted shortening.** "When the server is full, choosing which request to shorten — based on whether a waiting request can still make its deadline — beats both always-short and cut-whenever-full." Potentially novel, but it needs a working rule, a measured advantage, and confirmation on untouched questions.

The best outcome for this week is not a finished study. It is a confident, written choice between these two, backed by evidence. Everything below serves that choice.

## Where we are (one minute)

- The server works on two requests at once. A request's **thinking allowance** is how many tokens it may spend reasoning before it must answer. Lowering it mid-answer is a **cut**.
- We normally allow 16,384 tokens; at two or more requests waiting, we drop to 2,048.
- Letting the policy change its mind mid-answer beat deciding once, when the request first starts: 12 vs 8 correct-on-time out of 24 in development, and 51 vs 39 out of 96 under pressure in the separate 24-question test. Overall correctness was equal.
- Then "always 2,048" was tested. It tied our policy in a late burst and beat it under constant pressure, with fewer tokens and less time.
- The diagnosis found why. With only two slots, **one waiting request already means the machine is full**. Our trigger waits for a second one, so a long request can keep thinking while someone waits — and at the tail of a workload it may never be cut at all.
- One thing remains untested: **does thinking past 2,048 ever produce a better answer on this task?** If not, no controller cleverness can help.

## The main experiment

One comparison answers the premise and the fix together. Four policies, three workloads, 24 questions, two order-reversed runs: **576 measured answers**.

**Policies:** fixed 2,048 (the current champion), fixed 4,096 (does a longer fixed allowance ever help?), current live (cuts at two waiters), one-waiter live (cuts at the first waiter). All four share the same model, GPU type, engine, two slots, answer allowance, and the fixed phrase that ends thinking and starts the answer.

**Workloads:**

- **One at a time.** Each request runs alone with a deadline set so timing is not the point. Answers the premise: what does extra thinking buy with no queue? The two live policies should behave identically here; if not, something is wrong.
- **Constant pressure.** Requests arrive faster than they finish. Does the fix recover "always 2,048" efficiency?
- **Slack → rush → recovery.** Eight slow arrivals, eight fast, a pause, then eight slow. The only workload where adapting can win by design.

**Rules, written before launch.** A correct final answer received before its deadline is the primary measure. Also report eventual correctness, median and slowest completion time including queueing, queue wait, thinking tokens, total tokens, and cuts that took effect. Under pressure, no workload may end with more than one fewer correct answer than fixed 2,048. Report workloads separately. Nothing changes after results are seen.

**Questions.** The original 100-question development pool, minus those used in the last comparison, the timed setup runs, and the mechanics check, picked by a fixed published rule. Nobody chooses by looking at answers or difficulty. The untouched 376 stay untouched.

## The targeting check

This is the test that decides whether the ideal path is real. No new system this week; just enough to know whether the idea discriminates.

**Plain idea.** When the server is full, do not cut "whatever is running." Cut at most one request, and only if that specific cut would let a specific waiting request finish before its own deadline. If several qualify, pick the one that frees the slot soonest. If no waiting request can still make it, do nothing.

**What we build.** Give the controller each request's deadline; today only the offline scorer knows deadlines. Estimate two numbers from saved data: time from a cut to a finished answer (about 9.5 seconds in the observed cases) and expected wait in line. Run the rule in **shadow mode**: it records what it would do without acting.

**What we learn.** Apply it offline to Week 4 records. How often does it choose a different request from "cut whenever full"? Do the differences look plausible, or does it always agree? If it always agrees, this version of the ideal path is dead and we take the backup. This is a decision test, not a result.

**Optional, only if everything else is done:** a 72-answer pilot (12 questions × 1 pressure workload × 3 policies × 2 runs). Preliminary, and skipped without regret.

## How we split the work

Three lanes. A/B/C are role labels; fill in names at Monday's kickoff.

- **A, Builder** — code, the mechanics check, GPU runs, collection, packaging. About 4.5 days.
- **B, Analyst** — rules written first, saved-record questions, analysis, the premise and fix verdicts. About 4 days.
- **C, Explorer** — deadline input, targeting rule, offline discrimination check, path memo, ACER request. About 3.5 days.

Write only in your own folder; announce any change to the shared campaign folder. If a lane stalls, take the next unclaimed task.

## Tasks

**A — Builder**

- **A1. Implement the one-waiter cut.** The smallest fix to the diagnosed blind spot. *Done when* both triggers are selectable, the existing controller is unchanged, and the CPU tests pass.
- **A2. Freeze the plan and run the mechanics check.** Questions, workloads, deadlines, order, seeds, rules, compute cap; then prove each request gets its budget decision before generating, requests overlap, and a cut lands mid-answer. *Done when* the plan is saved and the gate passes. Gate runs do not count as science.
- **A3. Run the main experiment.** One-at-a-time first, then the two pressure workloads. *Done when* three jobs are launched or complete, with IDs and output paths recorded.
- **A4. Collect and score.** Keep every failure; no reruns for an unfavorable result. *Done when* all 576 answers are accounted for and the coverage audit passes.

**B — Analyst**

- **B1. Cheap questions from saved records.** (a) How often did thinking pass 2,048, and did it ever help? (b) How long from a cut to a finished answer? (c) Would waiting one or two seconds have avoided any cut? (d) Did any cut hit the wrong request? *Done when* a one-page memo has four numbers.
- **B2. Question-use record.** Confirm the chosen questions are already used, and reserve an untouched set from the remaining 376. *Done when* it is written down but not run.
- **B3. Write the analysis rules.** Primary measure, quality guard, per-workload reporting, and what counts as a premise or fix result. *Done when* saved before any outcome is seen.
- **B4. Analyze the main experiment.** Premise verdict and fix verdict, per workload, with paired per-question changes. *Done when* two tables and one figure are ready.
- **B5. Question-hardness breakdown.** Which questions, if any, gain from more thinking, and is that visible before the answer? *Done when* a short memo feeds the path choice.

**C — Explorer**

- **C1. ACER request.** One manual request, sent Monday, logged, then ignored. Not a dependency for anyone.
- **C2. Deadline input and shadow rule.** Deadlines reach the controller path; the rule logs intended cuts without acting. *Done when* a shadow log exists on saved records and behavior is unchanged.
- **C3. Offline discrimination check.** Apply the rule to Week 4 records and compare its choices with "cut whenever full." *Done when* a table shows how often it differs and on what kinds of states.
- **C4. Path memo.** What the targeted-shortening path would require, what gain is plausible, what the risks are, and what evidence would confirm it. *Done when* one page is ready for Thursday.
- **C5. Optional pilot.** Only if A and B are done and C3 looks strong. *Done when* 72 answers are scored, labeled preliminary.

## By Thursday morning

Each person brings **one saved artifact, one finding, and one risk**. We should also have:

- The one-at-a-time results complete and scored; the two pressure workloads complete or clearly on track.
- A **premise verdict**: did any question become correct only with more than 2,048 tokens, in both runs?
- A **fix verdict**: does one-waiter match fixed 2,048 under pressure without losing more than one correct answer?
- A **targeting verdict**: does the rule ever choose a different request from "cut whenever full"?
- A provisional path choice, written down.

**Take the ideal path** only if all three verdicts point that way: the premise is alive, one-waiter still leaves a quality gap, and targeting discriminates. **Take the backup** if the premise is dead, if one-waiter already matches fixed 2,048 with no quality loss, or if targeting does not discriminate. If the data is incomplete, narrow the week to the one-at-a-time and constant-pressure results and default to the backup. If the premise is dead, use the remaining days to prove it and to say what would have to change — harder questions, a different model — for it to matter.

By Monday: the written decision with its evidence, the results package and reproduction commands, the question-use record with an untouched set reserved, and a one-page handoff.

## If results send us sideways

| If this happens | We do this | Owner | Cost |
|---|---|---|---|
| No question benefits from more than 2,048 | Stop the targeting work. Write the negative result. Leave "change dataset or model" for next week. | B | 0 |
| Benefit appears only on a few questions | Check what predicts them (prompt length, first 500 tokens, problem type). Propose it for next week; do not build it now. | B | 0.5 d |
| Long thinking helps on many questions | Plan a larger or harder question set, or a second model, for next week. Do not start it now. | B | 0.25 d |
| One-waiter already matches fixed 2,048 with no quality loss | No room for targeting. Go straight to the backup. | A + B | 0 |
| One-waiter closes the time gap but loses two or more answers | Targeting is the right path. Prioritize C3 and C4. | C | — |
| Too few questions to see a difference | Add 24 more from the used pool; label the result preliminary. | A | 2 GPU-h |
| Campaign mechanically broken | Stop. Repair. Keep the failed run visible. Do not interpret partial data. | A | — |
| GPU time short | Drop the changing-load workload first, and say that claim is untested. | A | 0 |

## Compute and housekeeping

16 GPU-hours, split 12 for the main experiment and 4 for anything else. Same GPU type for every job; a hardware change restarts the comparison. One job per workload, at the same time when possible. No automatic retries. Estimate runtime from saved request times before submitting. New work goes in `week5/`; `week4/` is read-only.


