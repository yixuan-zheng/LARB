# LARB — Load-Adaptive Reasoning Budgets

Preliminary experiments on adapting reasoning budgets to serving load. Start with the [burst comparison](BURST-POLICY-REPORT.md), then the [serving proof](SERVING-PROOF-REPORT.md). This package contains completed experiments; running a launcher submits new GPU work.

## Package map

| Location | Contents |
| --- | --- |
| `code/` | Baseline, budget control, grading, analysis, and CPU tests |
| `results/` | Stage 1 and Stage 2 raw outputs and reviewed scores |
| `stage3/` | Frozen 100-problem, six-mode comparison; raw outputs, scores, diagnosis, and figures |
| `serving-proof/` | Minimal vLLM adapter, concurrent proof, and audit evidence |
| `burst-policy/` | Frozen burst protocol, controller, real serving results, and analysis |
| Root reports | Plans, feasibility assessment, measured outcomes, and limitations |

Runtime environments, model weights, caches, unrelated experiments, and pre-inference failed-launch logs are excluded. Executed source snapshots and manifests are retained with personal paths removed. Their checksums describe the sanitized files distributed here.

## Current interpretation

Live updates improved correct on-time completions on one 12-problem development trace. Only one cutoff bound during ongoing generation; admission-only budgeting remains an essential missing control. Equal aggregate correctness does not establish accuracy noninferiority. Load-aware early exit overlaps with [LASER](https://arxiv.org/html/2606.31580v1); the broad idea is not a supported novelty claim. See [RESEARCH-ASSESSMENT.md](RESEARCH-ASSESSMENT.md).

Latest result: the [controlled burst-policy pilot](BURST-POLICY-REPORT.md) completed 36 measured attempts plus two calibration requests on one H100. Live updates produced 6 correct on-time answers versus 4 full-thinking and 3 arrival-only, with the same aggregate completed correctness as full (11/12). This passes the preliminary screen on one trace; admission-only control and a general quality guarantee remain unresolved.

Stage 1 runs ten MATH-500 development problems sequentially with normal thinking enabled. It does not change budgets or run load adaptation.

## Run on PACE

The launcher uses one L40S, the existing read-only Gemma Python environment (PyTorch 2.9.1+cu128 and Transformers 5.7.0), and a separate Qwen workspace and model cache. It does not modify the Gemma environment. Only PyTorch, Transformers, and huggingface_hub are needed by the runner.

For cluster execution, `PACE_PROJECT_ROOT` points to your prepared runtime workspace and `PACE_ENV_ROOT` to your Python environment workspace. These are local settings, not repository paths.

```bash
cd ${PACE_PROJECT_ROOT}
sbatch --output=results/slurm-%j.out code/run_stage1.sbatch
```

The runner defaults to the exact model and dataset revisions used in the saved baseline. They can be changed explicitly with `--model-revision` and `--dataset-revision`. Sampling uses a separate recorded seed per problem; exact numerical reproducibility across hardware or software versions is not guaranteed. Each saved run also retains its executed source and launcher.

## Read the results

Each run writes:

- `manifest.json`: model and dataset revisions, runtime, GPU, settings, completion status.
- `problems.json`: the selected questions and reference answers.
- `requests.jsonl`: raw model output and token IDs, separated final answers, counts, timing, and preliminary exact-match scores.

From the local repository root:

```bash
python3 week3/larb/code/summarize_baseline.py week3/larb/results/job-JOB_ID
```

Exact string matching can reject mathematically identical LaTeX. Keep those raw scores and record manual review separately. A missing final answer counts as a failed answer.

Timing covers synchronized `model.generate` wall time after a short warmup; it excludes model loading, downloading, tokenization, and queueing. It is a sequential Transformers baseline, not a vLLM throughput measurement. Thinking tokens exclude the closing `</think>` marker; answer tokens include any terminal special tokens. The 16,384-token generation cap covers both thinking and answering, and is a safety limit, not a forced thinking budget.

Official model and sampling guidance: [Qwen3-4B model card](https://huggingface.co/Qwen/Qwen3-4B). Dataset: [MATH-500](https://huggingface.co/datasets/HuggingFaceH4/MATH-500).

## Stage 2: interrupt thinking in place

Read [STAGE2-REPORT.md](STAGE2-REPORT.md) for measured results and limitations.

`code/interrupt_probe.py` tests a 512-token thinking budget on the same ten prompts and seeds. It counts generated tokens before the first closing thinking marker, including the opening marker and whitespace, using Stage 1's convention. At the boundary, a logits processor forces only `</think>`. Generation then continues in the same call with the same KV cache and a separate 2,048-token answer allowance. It does not inject reference answers, restart generation, or replay the prefix.

The test records the cutoff event, observed closing marker, first post-close token, final response, any reopened thinking marker, answer-cap hits, and whether the pre-cutoff prefix matches Stage 1. Ending the designated thinking block does not guarantee that the answer text contains no further reasoning.

On PACE, from the experiment workspace:

```bash
sbatch --output=results/slurm-%j.out code/run_stage2.sbatch
```

Locally:

```bash
python3 -m unittest discover -s week3/larb/code -p test_budget_control.py -v
python3 week3/larb/code/summarize_interrupt.py week3/larb/results/stage2-job-JOB_ID
```

The observer synchronizes to inspect each generated token. Timing includes this instrumentation, so comparison with Stage 1 is descriptive rather than a controlled serving-speed benchmark. Mathematical correctness is reviewed separately from mechanical budget enforcement.

The targeted cue follow-up is `code/run_stage2_cue.sbatch`. It tests problem indices 0, 1, and 9 using `--transition cue`; it is not a full ten-problem evaluation. The cue adds 14 forced tokens after the 512-token normal allowance, including the closing marker and trailing newline.

## Stage 3: six modes on 100 matched problems

Read [STAGE3-REPORT.md](STAGE3-REPORT.md). All 600 attempts are complete. No tested shorter configuration met the observed three-point accuracy floor, despite substantial time savings.

`stage3/protocol.json` contains the settings frozen before generation. `stage3/problems100.json` is the selected data. The GPU launcher splits the run into 30 tasks, each processing 20 problems, with at most six L40S GPUs active. Raw outputs, executed source, and manifests are under `stage3/results/`.

On PACE, in the existing experiment workspace:

```bash
sbatch --output=stage3/logs/slurm-%A_%a.out code/run_stage3.sbatch
```

Finished tasks exit without generating new answers. Partial tasks resume their atomic per-request records. Run only one worker per task directory. For an independent repeat, copy only the protocol and problem input files into a new root and use the runner's `--root` argument; update the launcher accordingly.

For CPU grading and plotting, use a separate environment with `stage3/requirements-analysis.txt`:

```bash
python code/grade_stage3.py --root stage3
MPLCONFIGDIR=/tmp/qwen-stage3-mpl python code/analyze_stage3.py --root stage3
```

From the local repository root, use `week3/larb/code/` for the script paths and `week3/larb/stage3` for the root argument. Existing grading includes six documented multi-box extraction corrections in `stage3/manual-review.json`. Those corrections are tied to raw-record hashes and must be reviewed afresh for an independent repeat.

The analysis directory contains a six-row summary, per-problem CSV, paired bootstrap intervals, and the accuracy/time plot. The validation and accounting files record the completeness checks and actual GPU allocation.
