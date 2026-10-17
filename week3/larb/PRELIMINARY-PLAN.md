# Preliminary implementation plan: load-adaptive reasoning budgets

## What we want to find out

Rustam's idea is to shorten a model's thinking when the server gets busy, including requests that are already running. When the server is quiet, requests can use the full thinking budget.

For preliminary testing, we need to answer three questions:

1. Does shorter thinking save enough time while retaining useful answer accuracy?
2. Can we end thinking on a running request and still get a final answer?
3. During a burst, does changing budgets mid-request help more than choosing budgets only when requests arrive?

Implement these in order. Each stage should leave a small, runnable experiment and saved results. Do not build a general scheduler before the first two questions have promising answers.

## Stage 1: Get one model running and establish a baseline

Start with one Qwen3 reasoning model that fits the available GPU. Confirm the exact checkpoint and serving version during setup. Use a separate environment from the existing Gemma experiments.

Steps:

1. Load the model and run a few math prompts through its intended chat template.
2. Check how thinking ends and how the final answer is represented.
3. Run about 10 MATH-500 problems with full thinking and with non-thinking mode, if supported.
4. Save the complete output, extracted answer, correctness, token counts, and elapsed time for each request.
5. Record the model revision, software versions, decoding settings, and GPU in a run manifest.

Here, "full thinking" means no extra thinking restriction beyond a documented safety cap. Mark any request that hits that cap.

**Deliverable:** A baseline runner and a results file that we can reproduce.

**Checkpoint:** The model runs reliably, answers can be scored, and thinking tokens can be distinguished from answer tokens. Fix these issues before adding budget control.

## Stage 2: Add a thinking budget to individual requests

Build the simplest working budget mechanism first, using one request at a time. Check what the selected runtime supports before choosing an implementation.

Steps:

1. Count generated thinking tokens for each request.
2. At the budget, use a supported transition or an explicit continuation mechanism to ask the model to finish thinking and answer.
3. Give the final answer a separate token allowance.
4. Log when the budget is reached, when the transition takes effect, and when the final answer finishes.
5. Check the behavior on roughly 10 prompts with short and long thinking budgets.

Stopping all generation at the thinking limit is not a working implementation: we need a final answer. If transitioning requires restarting or replaying the prefix, include that overhead in timing and label the method clearly.

**Deliverable:** A runner that accepts a thinking budget and returns a scored final answer.

**Checkpoint:** Budget enforcement works consistently. Report failed transitions, missing answers, and extra tokens after the cutoff rather than dropping those requests.

## Stage 3: Measure the basic accuracy and time tradeoff

Use 100 fixed MATH-500 problems for development. Keep the other 400 untouched during preliminary tuning.

Compare:

- Full thinking.
- Non-thinking mode, if supported.
- Thinking budgets of 256, 512, 1,024, and 2,048 tokens.

Use the same problems, prompts, answer allowance, and decoding settings across configurations. Warm up the model before timing. Save individual outputs, not just averages.

Measure:

- Answer accuracy, counting failed or missing answers as incorrect.
- Actual thinking tokens and answer tokens.
- Median and p95 completion latency.
- Budget-transition failures and safety-cap hits.

Plot accuracy against measured completion time. Select one or two shorter budgets for the next stages.

**Deliverable:** A comparison table, an accuracy-versus-time plot, and the selected budgets.

**Checkpoint:** Look for a meaningful reduction in time with a tolerable accuracy drop. As a provisional screen, aim for at least 25% lower median completion time and no more than a 3 percentage point accuracy drop from full thinking. With 100 problems, this is a rough screening rule, not proof that a tight quality floor holds. If no setting looks promising, stop and review before building load adaptation.

## Stage 4: Make the budget changeable while a request runs

Extend the working budget mechanism so a request's limit can change after generation starts.

Steps:

1. Start a request with the full thinking allowance.
2. Trigger a budget reduction at a known point while it is still thinking.
3. If it has already passed the new limit, request the answer transition at the next supported opportunity.
4. Once a request enters its answer phase, leave it there. Do not interrupt the answer or resume thinking.
5. Repeat on roughly 30–50 development problems, including problems that normally think for a long time.
6. Run a small concurrent batch and confirm that changing one request does not change every request's budget.

Measure the delay from the trigger to the transition, time until the final answer, correctness, and total elapsed time. Compare against full thinking and the matching fixed-budget run.

When the fixed and updated budgets produce the same prefix and transition, use their agreement as an implementation check. The load experiment in Stage 5 tests the benefit of deciding later.

**Deliverable:** A working per-request budget update and a log showing that it takes effect during generation.

**Checkpoint:** The update must save actual execution time and still produce usable answers. If the runtime cannot update an active request, record that limitation. An abort-and-restart workaround needs its own timing check before we treat it as useful.

## Stage 5: Add one simple load rule and run a small burst test

Use the serving runtime's existing batching and scheduling. Add a small controller that reads queue length and updates thinking budgets. Keep batching, admission limits, and other serving settings the same across policies.

Implement four policies:

| Policy | Behavior |
| --- | --- |
| Full thinking | Every request keeps the full allowance. |
| Fixed short budget | Every request uses the selected shorter budget. |
| Budget chosen at arrival | Choose full or short using queue pressure when the request arrives; keep that choice. |
| Budget updated mid-request | Use the same arrival rule, and also shorten active thinking requests when queue pressure rises. |

Start with one queue threshold, checked at a fixed interval. Log both settings. Give the two adaptive policies the same budget choices and a small, equal amount of development tuning. For this pilot, a shortened request stays shortened; new requests can receive full budgets again when the queue clears.

Test three arrival patterns:

1. **Quiet:** Check whether the adaptive policies retain full-thinking behavior when capacity is available.
2. **Steady near capacity:** Compare against a fixed short budget.
3. **Burst after requests have started:** Launch long-thinking requests, then inject a burst while they are still thinking. This is the main test of mid-request control.

Reuse existing arrival-trace inputs where helpful, but measure the new model's capacity before setting arrival rates. Do not reuse Gemma timing estimates. Use the same problem order and arrivals for each policy, repeat with at least three arrival seeds, and log actual burst timing relative to active thinking requests.

Measure:

- Correct answers completed within a fixed end-to-end deadline per second.
- Overall answer accuracy.
- Median and p95 completion latency, measured from request arrival.
- Queue delay, number of shortened requests, and time for the queue to clear after a burst.

Choose the deadline from separate development calibration before comparing policies. Use one common observation window per replay; allow outstanding requests to finish for scoring, and report unfinished or failed requests. Token-streaming latency alone does not capture how long users wait for a final answer.

**Deliverable:** One policy comparison table, a queue-over-time plot, and request logs showing when budgets changed.

**Checkpoint:** Does mid-request control beat both the fixed short budget and the arrival-only policy in the burst case without an obvious accuracy collapse? A provisional target is a 10% improvement in correct-and-on-time answers per second while remaining within 3 percentage points of full-thinking accuracy. Treat small differences as inconclusive at this sample size. A win over full thinking alone is not enough to support the mid-request idea.

## Stage 6: Write a short preliminary result

Summarize what ran, what failed, and whether another round is justified. Include the model and runtime settings, raw result paths, the accuracy–time curve, the burst comparison, and limitations.

Choose one next step:

- **Continue:** Shorter thinking is useful, active requests can be updated, and the burst comparison shows a promising advantage over arrival-only decisions.
- **Fix the implementation:** The mechanism is not reliable enough to judge the idea.
- **Stop this setup:** Budget cuts lose too much accuracy, save too little time, or offer no useful advantage over simpler policies.

A promising pilot justifies a larger held-out evaluation. It does not establish novelty, a general quality guarantee, or a production-ready controller.

## Suggested implementation layout

Keep new code and results under `week3/larb/`:

```text
code/          Baseline runner, budget control, scoring, and burst replay
configs/       Model, budget, policy, and workload settings
results/       Per-request outputs, timing logs, and run manifests
REPORT.md      Preliminary findings and the next-step decision
```

The first implementation milestone is **Stages 1–3: a working budget mechanism and an accuracy-versus-time curve**. Only then add active-request updates and load control.
