# Checkpoints

We are starting from a working interruption mechanism and a small burst pilot. The missing piece is a fair admission-only comparison. The sequence below takes us from that comparison to a decision about further research.

Each task has smaller stopping points. Finishing one is enough for a useful session; nobody needs to complete a whole task before handing it over. The next person should continue from the evidence in the [handoff](HANDOFF.md), not repeat the previous person's work.

The route is not fixed regardless of results. A failed check may send us back to a repair; a negative result may take us directly to the final assessment.

## 1. Make the admission-only comparison work

We need to choose a request's budget just before it starts executing, then hold that choice fixed. Live control must make exactly the same initial choice and differ only by allowing later reductions.

**1A — Find and document the decision point.** Inspect the current service and adapter. Identify where a request first executes and where the queue snapshot comes from. Leave a short note with code locations and the intended event order. This is a useful stopping point even before implementation.

**1B — Implement the two behaviors.** Add admission-only budgeting and align the live policy's initial decision. Check that admission-only never changes later, that live changes target the right request, and that natural closure prevents further cuts. Stop with a commit and the CPU checks that passed; do not describe those as GPU validation.

**1C — Verify it under concurrency.** Prepare and run one bounded smoke test on available compatible hardware. Show that admission happens before generation, that requests overlap, and that a live cutoff takes effect while generation is already underway without stopping the answer. Save the configuration, events, and validation result. If the job is queued or running, record its ID and collection instructions and hand it over.

**Move on when:** the four modes run through one harness and the admission/live distinction is visible in the records.

**If it does not work:** fix the specific mechanical problem here. If no cutoff occurs, inspect timing before changing the smoke trace. If no GPU is available, stop with a runnable configuration and continue only CPU work or preparation; do not mark the smoke test passed.

## 2. Find out whether live updates add value

The first quality comparison should be small enough to diagnose. Its purpose is to tell us whether the live feature deserves more work, rather than to establish a general accuracy guarantee.

**2A — Save the comparison plan.** Select development questions and a trace with a burst after initial requests have started thinking. Choose deadlines, policy order, repetitions, and resource limits before seeing the results. State what improvement would justify continuing and what quality loss would be unacceptable. Check that replay and scoring handle late, wrong, capped, and failed responses.

**2B — Run and collect the comparison.** Execute matched runs for full thinking, arrival-only, admission-only, and live updates. Keep every attempt. A safe handoff includes completed and pending runs, active job IDs, output paths, and the next collection command.

**2C — Produce the first result table.** Validate that the runs are comparable and complete. Report correct on-time answers, eventual correctness, latency, failures, and actual live cutoffs. State whether live beat admission-only, tied it, lost to it, or left the question unresolved.

**Move on when:** we have an informative comparison to explain in Task 3. A negative result still moves the research forward.

**If it does not go as planned:** a run with no live cutoff cannot tell us the value of interrupting ongoing reasoning. An incomplete run cannot silently become a complete score. Diagnose the issue and save a bounded repair plan. If conditions change, identify which matched runs need repeating. Do not repeat experiments indefinitely to get a favorable outcome.

## 3. Explain what happened

Before changing the controller, understand which requests and events caused the result. We need to distinguish useful capacity release from incidental changes in sampled answers or measurement errors.

**3A — Select the cases that matter.** List requests whose deadline outcome or correctness changed. Include binding and nonbinding cuts, lost correct answers, rescued failures, and surprising timing differences. Link each case to its raw record.

**3B — Reconstruct the sequence.** For those cases, follow the intervention, answer generation, slot release, admission of queued work, and final completion. Check grading and timing. Write down what the logs establish and what remains only a plausible explanation.

**3C — Choose the next step.** Leave a short decision supported by the cases. It should tell the next person whether to validate the current candidate, make a specific improvement, repair the experiment, or close the direction.

**Choose the route from the evidence:**

- A useful result with no justified change goes straight to Task 5.
- A specific weakness worth fixing goes to Task 4.
- A grading or timing defect goes back to the affected comparison after repair. Rescoring is different from rerunning the model; preserve the originals.
- No meaningful advantage over admission-only can go directly to Task 7 as a negative or characterization result.
- An ambiguous mechanism may justify one targeted control, with a new plan and compute limit. Matching seeds alone does not resolve output divergence.

## 4. Make a targeted improvement, if the evidence calls for one

This task is optional. We should not add sophistication simply because we can. The change should address a weakness seen in Task 3, such as cuts that arrive too late or answer generation that consumes the saved time.

**4A — State the proposed change.** Explain the observed problem, the change, the expected effect, and the possible cost. Save a small development test plan. Someone can safely stop here before writing code.

**4B — Implement and check it.** Make the narrow change and verify its mechanics. Record what changed in the configuration or interfaces. Push the code and checks so another person can continue without reconstructing the intent.

**4C — Decide whether to keep it.** Compare the revision with the earlier candidate and admission-only as appropriate. Record whether the hypothesis held, failed, or remained uncertain. Keep losing variants in the record.

**Move on when:** we have selected a candidate for validation, including the option to retain the original.

**If the change fails:** revert it or leave it as an unsuccessful branch. Proceed with the earlier candidate if it remains promising, or go to Task 7. Another round needs a specific reason and a new bounded plan; this is not an unlimited tuning loop.

## 5. Check whether the benefit holds beyond development

Now test the selected candidate on questions and traffic that did not determine its settings. We want to know where it helps and what accuracy cost accompanies that benefit.

**5A — Freeze the evaluation.** Check which questions remain unexposed. Save the candidate, sample, low-load/burst/sustained-pressure conditions, deadlines, order, repetitions, analysis method, success criteria, and resource limit. State what strength of conclusion the sample can support.

**5B — Collect the evaluation.** Run complete matched comparisons and retain all failures. Stop safely with a list of finished and pending runs and instructions for any active job. If hardware changes, use a new calibration and complete matched comparisons on that hardware.

**5C — Assess the result.** Report the admission/live difference by condition, eventual accuracy, failures, overhead, and uncertainty. Say whether the benefit is broad, limited to a specific condition, absent, or still inconclusive.

**Choose the route:** a useful result goes to Task 6. A narrow result may go to Task 6 with a narrow claim, or directly to Task 7 as characterization. Unacceptable quality loss or no reliable benefit goes to Task 7.

If these results lead to tuning, those questions are now exposed. Return to diagnosis or revision with an explicit new plan rather than calling the same data untouched evaluation.

## 6. Work out what the result adds to prior work

The closest literature should already inform our design. Here we carry out the comparison needed to assess the surviving approach. We are not starting a broad literature survey at this point.

**6A — Specify the comparison.** Use the existing research assessment to select the closest relevant method. Check whether public code fits our setup. Write down the algorithm, settings, probing/cache costs, and any adaptation needed. Decide whether the comparison is feasible within the remaining stage budget.

**6B — Prepare the baseline.** Implement or integrate the selected method and check that it behaves as specified. Record deviations. A safe handoff includes the code, configuration, checks, and anything still preventing a fair run.

**6C — Compare and interpret.** Run a saved, bounded comparison under disclosed conditions. Explain whether LARB adds a useful behavior, offers a simpler tradeoff, overlaps existing work, or is worse.

**Move on to Task 7 with the conclusion the evidence supports.** A different implementation or GPU alone is not a novelty claim. If reproduction proves infeasible, record what was tried and what is missing; finish with novelty unresolved rather than relabeling an approximation as a faithful baseline.

## 7. Close the stage

The endpoint is a clear account of what we learned and whether more work is justified. It does not require a positive result.

**7A — Make the evidence usable.** Organize the new code, configurations, raw outputs, scores, checks, and resource accounting. Provide a reproduction path and identify missing or skipped comparisons. Keep Week 3 evidence in place and link to it.

**7B — Write the assessment.** Answer the stage question. Explain the quality cost, conditions where the controller helps or fails, uncertainty, and relationship to prior work. Distinguish demonstrated findings from suggestions and untested ideas.

**7C — Check and finish.** Verify the report's numbers against saved results. Push the final artifacts and state whether to continue, reframe, or stop. If continuing, name the next research question rather than automatically launching another experiment.

A useful negative result, a narrow characterization, or a well-supported inconclusive result can all close this stage. Further experiments need a new question and plan.
