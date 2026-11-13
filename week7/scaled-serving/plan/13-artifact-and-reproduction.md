# 13. Artifacts, freezing and reproduction

The project's strongest habit is that a result can be re-derived months later from stored records.
The scaled rig must keep that habit at ten times the data volume. This file is the checklist.

## 13.1 Directory layout

```
week7/scaled-serving/
  README.md                     # orientation and index
  PLAN.md                       # execution plan
  binder/                       # 01-06: the information set behind the plan
  plan/                         # 07-13: this document set
  rig/                          # executed code; copied/refactored from week5/6
  runs/
    <job-id>-<stage>/           # e.g. 7100001-gate, 7100002-main
      manifest.json             # job id, stage, commit, source-lock hash, start/end, GPU
      config.json               # frozen config for this stage
      source-lock.json          # hashes of every executed source file
      phases/
        <condition>-<arm>/
          phase.json            # planned/actual counts, horizon, injection, drain
          requests.jsonl        # one record per request, all fields in plan/07-rig-design.md 7.6
          tokens/               # raw token ids for scored requests (compressed)
          scheduler/            # sampled snapshots; full around cuts
          gpu.jsonl             # 1 Hz utilisation/memory samples
          cuts.jsonl            # cut events
      analysis/
        analysis.json
        paired.csv
        report.md
  DATASETS.md
  TRACE.jsonl                  # or one per condition under runs/.../traces/
  PROTOCOL.md
  REPORT.md
  reproduce.py
```

`runs/` is gitignored except for the manifests and the final report. Raw token IDs and scheduler
snapshots stay on scratch storage; the committed package contains the derived records needed to
reproduce the headline numbers, as the week 6 handoff does.

## 13.2 Freeze list

Before the main run, hash and record:

- Every executed `.py`, `.json`, `.sbatch` and `.sh` file in `rig/`.
- The model revision and the tokenizer files.
- The dataset manifest: id, revision, source file SHA-256, row count, license, exposure tag.
- The trace bytes and the trace generator seed.
- The frozen config: arms, budgets, threshold, persistence, progress window, deadline, concurrency,
  answer contract, sampling parameters.
- The analysis code and the grading code.
- The Slurm resource request and the job script.

After the run, verify that the executed hashes match the frozen ones. If they do not, the run is a
different experiment and is labelled as such.

## 13.3 Naming and pairing

- `request_id = {condition}--{arm}--{question_id}--{seed}` for signal; `...--filler--{index}` for
  filler.
- `question_id` includes the pool prefix, e.g. `aime2026-017`, `hmmt-nov2025-004`.
- `phase_id = {block}--{condition}--{arm}`.
- The same question/seed/offset/deadline appears in every arm; a validator enforces it and writes a
  `pairing.json` with the intersection and any mismatch.
- A phase that is repeated keeps its original `phase_id` plus `rerun-1`; the original remains in the
  record and is marked invalid if it failed injection.

## 13.4 Reproduction

`reproduce.py` must run from the repository root with the analysis venv (no GPU, no vLLM) and:

1. Verify the source-lock and dataset-manifest hashes.
2. Rebuild the per-request table from `requests.jsonl`.
3. Re-grade a sample of raw answers with `math_verify` and compare to the stored flags.
4. Recompute the per-question paired table and the primary cluster bootstrap.
5. Reproduce the headline table in `REPORT.md` within a stated tolerance (bootstrap intervals may
   differ by Monte Carlo noise; the point estimates must match exactly).
6. Print a pass/fail summary and a hash of the regenerated `analysis.json`.

The reproduction script is part of the deliverable, not an afterthought. A result that cannot be
reproduced on CPU is not a result.

## 13.5 Grading review queue

Every wrong, ambiguous, capped or unparsable answer is retained with:

- request id, question id, seed, arm, condition;
- raw output text and token ids;
- extracted answer, reference answer, Math-Verify result;
- finish reason and cap flag;
- reviewer note and, if corrected, the reason and hash.

Corrections follow the week 3 protocol: a correction is recorded, hashed and reported separately.
The main analysis uses the uncorrected score; the corrected score is a sensitivity check. No
correction is made after the primary analysis has been seen.

## 13.6 Reporting checklist

Every report must include:

- The frozen hypothesis and the operational H1-H4.
- The arm definitions and the exact pressure/cut rule.
- The cohort: pools, item counts, exclusions, exposure tags, fresh subset.
- The trace: arrival process, rate, burst offsets, deadline, warm-up, drain.
- The engine: model revision, vLLM/torch/transformers, concurrency, context, graphs, cache,
  sampling.
- The primary numerator and denominator per arm and condition, with CIs and the realised MDE.
- Accuracy, deadline attainment and cap marginals, so the joint metric can be decomposed.
- Per-question paired changes, not just totals.
- Latency, tokens, throughput, preemptions, KV and GPU utilisation.
- Manipulation checks and any invalid phase.
- Failures: caps, missing, errors, late, restarts, injection lag.
- Limitations: sample size, ICC, contamination, one block, one model, one GPU.
- The decision: supported, refuted or unresolved, and the next action.

## 13.7 Licensing and attribution

The MathArena datasets are used under their recorded terms (the AIME 2025 manifest records
CC BY-NC-SA 4.0). `DATASETS.md` keeps the dataset id, revision, license and attribution. Raw
question text is not redistributed outside the terms. The Qwen3-4B model is used under its own
license; the model files stay in the shared model directory, not in the repository.

## 13.8 Retention

Keep the raw records for at least the life of the project. The committed package keeps the derived
records, the source lock, the trace hashes and the reproduction script; scratch storage keeps the
full token and scheduler records. A run whose raw records are lost is a run that cannot be audited;
the manifest must say where they are.

## 13.9 What not to do

- Do not silently drop a capped or missing request.
- Do not re-run an arm because its result is unfavourable.
- Do not change the threshold, deadline, dataset or grader after seeing the main scores.
- Do not report a rate without its denominator.
- Do not claim a 3-point accuracy preservation from a 200-question cohort.
- Do not call a 2-3 point difference a tie when the CI spans zero.

