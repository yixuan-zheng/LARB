# Handoff

Read this before working and update it before leaving. **Pull first; push your changes and results when you finish.** Keep the newest entry at the top and retain earlier entries below it.

## Starting point

Week 3 completed the interruption proof and the three-policy burst pilot. The next piece of research is the missing admission-only comparison.

- **Next checkpoint:** 1A in the [checkpoint plan](CHECKPOINTS.md): identify where the budget can be chosen before first execution.
- **Starting code:** the existing [service](../week3/larb/burst-policy/server.py), [adapter](../week3/larb/burst-policy/adapter.py), and [policy logic](../week3/larb/burst-policy/policy.py).
- **Existing evidence:** [serving proof](../week3/larb/SERVING-PROOF-REPORT.md) and [burst comparison](../week3/larb/BURST-POLICY-REPORT.md).
- **Week 4 implementation and experiments:** not started by these documents.
- **Active Week 4 jobs:** none submitted as part of this setup. Check the actual scheduler before submitting; this document is not a live queue monitor.

## What to leave for the next person

Use this short format. Include real paths and commands once they exist; do not invent a command for a tool that has not been built.

```text
Checkpoint and state: for example, 1B partially implemented
Person / branch / commit:
What changed:
What I verified: command and result; distinguish CPU checks from GPU tests
Results and configuration: paths
Running job: ID, output location, and how to collect it, or none
What is still wrong or unknown:
Next action: one specific step or command
Compute used / remaining: if a run is in progress
```

It is fine to stop halfway through a checkpoint. Push the partial work on a named branch and say exactly what is unfinished. Do not mark a checkpoint passed because code was written but not verified.

If an experiment is running, the next person should collect that job rather than submit another copy. If a result is surprising or negative, preserve it and describe the uncertainty; do not quietly replace it with a rerun.

If someone else is working, publish which part you are taking before editing the same files. A short handoff and a pushed commit should be enough to continue; long activity reports are unnecessary.
