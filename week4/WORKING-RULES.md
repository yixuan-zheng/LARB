# Working rules

These rules keep our work compatible. They leave room to change the controller and experiments as we learn. The [checkpoints](CHECKPOINTS.md) describe what to do next.

## Shared starting point

| Area | What we use |
| --- | --- |
| Serving | vLLM, starting from the existing [burst service](../week3/larb/burst-policy/server.py) and [adapter](../week3/larb/burst-policy/adapter.py). The working version is 0.11.2. |
| Model | Qwen3-4B with the same checkpoint, tokenizer, and chat template as Week 3. The exact model settings are in the [saved experiment specification](../week3/larb/burst-policy/spec.json). |
| Data | MATH-500. The [saved protocol](../week3/larb/stage3/protocol.json) identifies the dataset version. Questions 0–99 have already been used for development; check exposure before selecting evaluation questions from 100–499. |
| Traffic | A saved schedule of requests, replayed without waiting for earlier requests to finish. Reuse the same schedule for every policy being compared. Start from the existing [runner](../week3/larb/burst-policy/run.py). |
| Grading | Math-Verify 0.9.0 and the reviewed [grading code](../week3/larb/code/grade_stage3.py). Keep the [analysis dependencies](../week3/larb/stage3/requirements-analysis.txt) separate from the serving environment. |
| Historical evidence | Keep the [Week 3 reports and results](../week3/larb/README.md) unchanged. Put new code, configurations, and results under Week 4. Import or reference reusable Week 3 code instead of copying whole directories. |

An environment change is allowed if needed for compatibility. Record it, verify that the adapter still behaves correctly, and use that environment for all policies in the comparison. Do not upgrade packages casually in the middle of an experiment. The [successful run manifest](../week3/larb/burst-policy/results/job-6320907/manifest.json) records the known-working runtime.

## Hardware is flexible

- Use an available GPU that fits the model and passes a concurrent smoke test. H100 is not required; L40S or another compatible device is acceptable after validation.
- CPU work does not need to wait for a GPU. Policy logic, grading, replay checks, and analysis can use small fixture records.
- Choose concurrency and context capacity to fit the device. If fitting requires different precision, quantization, or generation limits, record a new configuration and rerun the matched policies under it.
- Compare policies on the same GPU model/count and software settings. If hardware changes, start a new complete comparison; do not treat an H100 live run versus an L40S admission run as evidence about the policy.
- Set traffic rates and deadlines using development calibration on the chosen hardware, then keep them unchanged across compared policies.
- Historical launchers request H100 explicitly. Adjust resource requests before reusing them; a saved launcher is not a hardware-neutral setup command.

## What the four policies mean

| Policy | When the thinking budget is chosen |
| --- | --- |
| Full thinking | No load-driven reduction; the shared safety limit still applies. |
| Arrival-only | Once, when the server receives the request. |
| Admission-only | Once, immediately before the request first executes. |
| Live updates | The same initial decision as admission-only, with later reductions allowed while thinking continues. |

The main comparison is **live updates against admission-only**. They must start with the same rule so that later intervention is the difference we measure. This is a change from the previous pilot, whose live policy started with an arrival-time decision.

- Keep stock scheduling unchanged when isolating the four policies.
- Do not change a thinking budget after the request has naturally entered its answer phase.
- Finish a forced transition cue before normal answer generation resumes.
- Record both budget changes and cutoffs that actually take effect. A reduced budget that the model never reaches is not a successful interruption.
- The controller must not receive reference answers or grading results.

## What researchers can change

- Budget lengths, queue thresholds, update timing, and which requests are selected for cuts.
- Traffic patterns, concurrency, problem count, deadlines, and repetitions.
- Implementation details, tools, tests, and plotting methods.
- The closest-method baseline, provided its relationship to the published method is explained.

Use development runs to make those choices. Before an evaluation, save the candidate, inputs, settings, success criteria, analysis plan, and compute limit. If results lead to another change, give it a new configuration and label the earlier run honestly.

The [previous specification](../week3/larb/burst-policy/spec.json) provides starting values, not mandatory optimal settings. We do not need to design a more complicated controller unless a result gives us a reason.

## What counts as a useful result

- Primary success: a correct final answer, normal completion, and client receipt before the request's deadline.
- Measure elapsed time from scheduled arrival to final receipt on the client's clock. Include queueing, thinking, answering, and transport.
- Also record server-side events for diagnosis. Never subtract timestamps from unrelated clocks.
- Thinking caps, answer caps, missing finals, errors, and cancellations are failures. A correct number inside unfinished reasoning does not count.
- Report correct-on-time count and total requests. For a rate, divide the count by the same fixed observation window for all policies: the latest scheduled arrival plus its deadline, taking the maximum across requests.
- Let late requests finish under the common safety limits and report eventual accuracy separately. Keep timed-out and incomplete records visible.
- Report queueing, latency, binding cutoffs, token use, failures, and GPU allocation time alongside the primary result.
- Keep extraction problems separate from mathematical mistakes. Document any manual correction and apply the same rule across policies.
- Repeating the same questions does not create more independent accuracy examples. Report uncertainty; equal scores on a small sample do not establish a three-point accuracy guarantee.

For each matched comparison, keep the model, sampling, answer allowance, safety behavior, instrumentation, traffic, and deadlines consistent. Vary policy order using a saved plan. Identical random seeds do not guarantee identical outputs when batching changes.

## Experiments and records

- Give every run its own directory. Save the configuration, request schedule, source commit, environment, raw outputs, scored results, and validation summary.
- Keep failed attempts and rejected changes visible. Do not overwrite a run or quietly replace an unfavorable result.
- Set an allocation and attempt limit before submitting GPU work. A failure is a reason to diagnose, not to start an automatic retry loop.
- Put running job IDs, output locations, and collection instructions in the [handoff](HANDOFF.md). Check it before submitting anything.
- Record extra probing, generation, and caching costs when comparing a prior method. Describe adaptations as adaptations.
- The [research assessment](../week3/larb/RESEARCH-ASSESSMENT.md) identifies the closest work. A real concurrent implementation alone is not a novelty claim.

## Starting and finishing a session

- Pull the latest changes before starting. Read the handoff and claim the checkpoint you are continuing.
- If someone is already working, agree on file boundaries before making overlapping changes. Git is the shared record; a claim is not an automatic lock.
- Keep unfinished changes on a clearly named branch if they are not ready to integrate. Push that branch and record it in the handoff.
- Before leaving, push your code, configurations, results, and updated handoff. Include the verification command and the next concrete action.
- Do not commit credentials, model weights, environments, or caches. If an essential artifact is too large for Git, commit its summary, checksum, and an accessible retrieval location.
- Update shared interfaces and their checks together. Explain changes to scientific definitions so the next person does not unknowingly combine incompatible results.
