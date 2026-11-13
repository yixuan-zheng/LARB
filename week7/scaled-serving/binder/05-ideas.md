# 5. Ideas, unordered

A pool of individually motivated changes, not a plan, not a priority order, and not a ladder of
gates. Tags say which pressure an idea relieves: **[speed]** data per GPU-hour, **[realism]** how
much the setup resembles a service, **[policy]** the controller itself, **[measurement]** the
interpretability of whatever we get.

## Throughput: more data per GPU-hour

**1. Raise concurrency.** [speed] Go from 2 to 16/32/64 concurrent sequences and measure the
throughput curve before anything else. At two slots one request is already "the queue"; at thirty-two
the queue is real. Risk: KV memory caps concurrency at long contexts, and preemption starts to occur.

**2. Turn on CUDA graphs.** [speed] Eager mode was chosen for per-step token manipulation. If the
forced-cue path survives graph capture, decode throughput should improve substantially. Verify by
re-running one frozen condition and checking that the cue still lands on the exact token.

**3. Shrink the answer allowance.** [speed][realism] 2,048 tokens of answer is generous for an integer
result and is where 20-30% of AIME outcomes die. 256-512 tokens with a forced "Final answer:" opener
would cut request cost several-fold. Risk: hard items may need the space; measure cap rate per pool.

**4. Make thinking and answer budgets two separate knobs.** [speed] They are already separate
constants (4k or 8k for thinking, 2,048 for the answer) but have never been varied independently.
Sweeping them apart shows which one the accuracy actually depends on and which one merely costs time.

**5. Reclaim context.** [speed] 24,576 tokens was sized for 16k thinking plus a 2k answer. If the
workload is 4-6k, halving the context roughly doubles how many sequences fit in the KV cache
(very roughly 150 KB of KV per token for this model, so context length is the main memory lever).

**6. Batch the seeds instead of queueing them.** [speed][measurement] A "same question, eight seeds"
design currently means eight sequential requests. Sent together, it is one batch and eight times the
information per unit time, and it keeps the question-level pairing that makes the statistics honest.

**7. Pre-screen on a smaller model.** [speed] Threshold sweeps could be run on a 1.7B model and
confirmed on the target model, if a transfer check shows the ranking is stable. Risk: the whole point
may be that budget sensitivity changes with model size.

## Realism: make the load look like a service

**8. Use exogenous deadlines.** [realism][measurement] Replace "1.5 x slowest calibration request"
with a declared service-level objective, e.g. 1.0-1.3 times the reference policy's median completion
time. Then the on-time metric has room to move, and it means the same thing across rigs and datasets.

**9. Generate arrivals as a process, not a script.** [realism] Sustained overload at a chosen rate,
with bursts, is closer to real traffic than a fixed twelve-request trace and costs nothing extra to
run. The trace can still be frozen and hashed before measuring.

**10. Replay a real arrival trace.** [realism] A published serving trace would give realistic
burstiness and idle gaps. Risk: its length distribution and model do not match ours, so only the
*arrival pattern* should be borrowed.

**11. Mix difficulties deliberately.** [realism] Short easy requests plus long hard ones produce a
service-time distribution, keep the batch full, and make "who gets cut" an interesting question.
A single-difficulty pool makes every request identical from the scheduler's point of view.

**12. Add a second deadline class.** [realism][policy] Tight and loose tenants test whether a cut
should consider whose deadline is at risk rather than only how long the queue is.

**13. Make slack-to-burst-to-recovery the default condition.** [realism] It is the only recipe that
exercises all three behaviours (hold budget, cut, restore) in one run, and it already exists.

**14. Turn prefix caching on.** [realism][speed] Production engines cache. It also makes repeated
question designs much cheaper, since every policy and seed reuses the same prompt. Report prefill
cost so the savings are not confused with reasoning savings.

**15. Interleave policies inside one run.** [measurement][realism] Assign policies per request (or
per small batch) with a frozen, balanced assignment instead of running long blocks. This removes
run-order drift and thermal effects, at the cost of some cross-request interference.

**16. Always keep a no-queue control.** [measurement] A condition where nothing ever waits is the
proof that the controller does nothing when it should do nothing. It costs one arm and prevents the
most embarrassing failure mode.

## The controller itself

**17. Sample the middle of the static grid.** [policy] We have never run a 5k or 6k fixed budget, yet
4k to 8k is exactly where accuracy moves. A static 6k might match 8k accuracy at 4k-like cost, in
which case the adaptive mechanism has to clear a much higher bar. This is the cheapest single idea
in this file and it partly invalidates or strengthens the premise on its own.

**18. Define pressure relative to capacity.** [policy] "One request is waiting" was meaningful at two
slots and is meaningless at thirty-two. Candidate rules: waiting >= 25% of slots; waiting x expected
service time > remaining slack; or queue depth relative to the arrival rate. Pick one before running.

**19. Add persistence.** [policy] Require the queue to be non-empty for k consecutive snapshots, or
for a fixed dwell time, before cutting. Rationale: a momentary gap should not permanently shorten a
request. This is a real knob with a real failure mode (waiting longer can make the cut arrive too late).

**20. Cut a fraction, not a destination.** [policy] Replace "reduce to 4,096" with "halve the remaining
allowance" or "remove 2,000 tokens". It scales naturally to non-4k budgets and to requests that are
already close to their limit.

**21. Add a minimum-progress floor.** [policy] Do not cut a request that has generated almost nothing
(the cut saves little and may discard a promising start) or one that is almost done (nothing to save).
The window where a cut is worth taking is measurable from existing traces.

**22. Choose who gets cut.** [policy] Today every eligible running request is cut at once. Alternatives:
cut the newest, the least-progressed, the one with the most remaining budget, or the one whose answer is
least likely to change. This is the one place where per-request information could enter without a heavy
predictor.

**23. Trigger on a deadline, not on a queue.** [policy] Cut only when a specific waiting request would
otherwise miss its deadline, given queue depth and recent service time. Cruder and more robust than a
learned predictor, and directly aligned with the metric.

**24. Cascade the response.** [policy] Cut one request, re-check after a few scheduling steps, and cut
another only if the queue is still short of capacity. Prevents the current behaviour of cutting
everything in response to a brief spike.

**25. Keep the admission-only and entry-only arms.** [policy] The entry-timing branch was tested once
and rejected on a 24-request sample. Retaining both arms costs almost nothing at scale and separates
"the queue moved the budget" from "we interrupted someone".

**26. Test restoration explicitly.** [policy] Later arrivals already get 8k after pressure clears.
Make "does restoring the budget actually recover the lost accuracy" an explicit question rather than an
assumption.

## Model size

**27. Move up one model size.** [policy][realism] 8B fits comfortably; 14B and 32B need FP8 or AWQ on
one H100. Bigger models overthink more, which is exactly the regime where a budget lever matters. The
risk is that throughput per GPU-hour falls faster than the effect grows.

**28. Run a size bridge.** [measurement] Repeat one condition at two model sizes so the effect can be
compared rather than assumed to transfer.

## Measurement discipline

**29. Instrument the machine.** [measurement] Sample GPU utilisation, KV-cache occupancy, running and
waiting counts, and preemption events. Without this, "we saturate the device" is an assertion, and we
cannot tell a policy effect from a capacity effect.

**30. Set the effective sample size before running.** [measurement] Decide how many independent
questions and seeds are needed for a 3-point difference, using the variance already observed in our
own data, and refuse to interpret anything smaller.

**31. Pre-register few comparisons.** [measurement] Two or three arms, one primary metric, one
tolerance. Every extra arm multiplies the chance that the largest number looks like a finding.

**32. Charge the full mechanism.** [measurement] Count cue tokens, the discarded continuation, the
answer tail, and controller overhead in the cost of every policy, so "non-probing is free" is a
measured claim.

**33. Report a frontier, not a score.** [measurement] Accuracy against tokens and against latency, with
per-question deltas. A single winner column is what allowed six weeks of ties to look like progress.
