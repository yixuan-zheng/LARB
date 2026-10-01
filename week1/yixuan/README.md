# Yixuan — Week 1 scheduler and pilot results

This is a curated local handoff of Person C's work, with supporting performance/quality checks. Originals remain in the neighboring Week 1 folders. No model weights, credentials, or GPU job logs are included.

## Start here

- `decode/results/policy_comparison.png`: the main measured policy comparison.
- `decode/results/analysis.json` and `comparison.csv`: pooled and per-trace results.
- `decode/code/run_experiment.py`: real Gemma generation, queue replay, and width-selection logic.
- `scheduler/simulator.py`: the original CPU scheduler prototype. Its saved demo uses synthetic timings; it is not measured serving evidence.
- `supplemental/prefill/`: the separate prefill policy pilot.
- `supplemental/model-comparison/`: bounded Gemma/Nanochat timing and quality screening, plus earlier Nanochat implementation checks.

## Main Person C result

Real Gemma 3n execution on one L40S; three saved arrival traces, 120 requests per trace, four policies (1,440 replay requests). The presets retain all 35 layers and attention, changing only the published per-layer FFN capacities. Switching retains earlier KV history. The harness finishes each cohort before admitting another; it is not continuous batching.

| Decode policy | Correct and on-time answers/s | Exact-match accuracy | Latency SLO pass |
|---|---:|---:|---:|
| Fixed Large | 1.737 | 73.9% | 62.8% |
| Fixed Small | 1.355 | 66.7% | 56.4% |
| Request-level selection | 1.481 | 68.3% | 60.3% |
| Iteration-level selection | 1.538 | 67.5% | 63.1% |

Iteration-level selection beat request-level by 3.82% pooled, but only won one of three traces. It lost 11.50% against Large. It switched 95/360 requests and failed the five-percentage-point quality tolerance. **No-go for serving-engine integration based on this pilot.** This does not disprove better policies or optimized continuous batching.

TTFT target: <=1 second. Maximum inter-token gap: <=200 ms. Goodput counts exact-match-correct, on-time answers divided by full trace/drain duration. Quality is also assessed across all requests. Short answers averaged about five tokens; batches averaged about 2–3. Larger/longer regimes and GPU profiling remain unfinished.

The CPU simulator already executes fixed Large/Small, request-level and iteration-level policies on steady, burst and changing-length traces. It records request latencies and operation decisions. Its default SLOs are unset and quality eligibility is not enforced. It still needs calibrated timing coverage, quality restrictions, baseline tuning and sensitivity analysis.

## Supplemental findings

The prefill pilot also ran 1,440 real-GPU replay requests. Adaptive Small-prefill/Large-decode achieved 1.604 correct/on-time answers/s versus Large's 1.617: no demonstrated benefit. Fixed hybrid achieved 1.563. These results do not justify pivoting exclusively to prefill adaptation.

Gemma's controlled 200-example quality test: Large 74%; Small 67.5%; Large-to-Small after two tokens 73.5%; Small-to-Large 67.5%; alternating every two tokens starting Large 74.5%. Large-first schedules are promising on this task, but the extra correct alternating answer is not evidence of a general quality improvement. The experiment does not isolate early answer errors from prefix-history effects.

Both Gemma and Nanochat received a 24-example cloze screen, synchronized prefill/decode microbenchmarks and retained-cache switching checks. Decode savings were roughly 0–2% in the measured cells. At batch 8/context 256, dynamic Small prefill savings were about 18% for Gemma and 28% for Nanochat. The deep QA and overload pilots were **Gemma only**; no Nanochat scheduling conclusion is established.

## Directory and evidence

Each GPU experiment keeps `code/`, frozen `data/workload.json`, and `results/` together. Raw `quality_*.json` records contain generated answers and capacity histories; `replay_*.json` contains per-request outcomes and operation timelines; `trace_*.json` contains arrivals. JSON summaries, comparison CSVs and PNG plots make the result easy to inspect. `environment.json` records runtime metadata. `supplemental/model-comparison/results/environment.txt` is the recorded package inventory, not a portable installation recipe.

The only packaging code change is in the supplemental prefill runner: it now reads the original frozen workload instead of regenerating it from upstream SQuAD files. Saved results are otherwise preserved except redaction of machine-specific storage paths. Protocols below preserve the original predeclared rules.

## Run and verify

From this folder:

```sh
python3 scheduler/simulator.py --out scheduler/new-demo
python3 -m unittest discover -s scheduler/tests -v
python3 decode/code/validate_results.py
python3 supplemental/prefill/code/validate_results.py
```

GPU reruns require the existing CUDA environment and gated E4B checkpoint/tokenizer cache. Do not rerun into the saved evidence directory: copy the experiment into a separate working directory first, retaining its code/data and the decode `results/calibration-source.json`. Launchers use `EXPERIMENT_ROOT` and `GEMMA_ROOT` (your experiment directory and existing setup containing `gemma3n/` and `hf-cache/`). Set your own Slurm account/partition/GPU settings in `run_pace.sbatch`.

Gemma revision: `af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee`. Observed runtime: PyTorch 2.9.1+cu128, Transformers 5.7.0, Hugging Face Hub 1.32.0, safetensors 0.8.0. Analysis scripts use NumPy; plots additionally use Matplotlib. CPU simulation/validation use the standard library.

Nanochat comparison requires the author's external inference checkout (source commit `3337ff6bdffc0b4f6dcecd6fdad8ceb7f3c56a24`), its cached checkpoint and tokenizer. Its launcher takes `DECISION_ROOT`, `GEMMA_ROOT`, and `NANOCHAT_ROOT`; it is not a self-contained checkpoint package. Source: https://github.com/avitrost/nanochat-matformer-inference . Gemma presets: https://huggingface.co/datasets/google/gemma3n-slicing-configs . QA source: https://rajpurkar.github.io/SQuAD-explorer/ .

## What to hand back to A/B and what C does next

A: profile representative decode cells, extend the timing grid, and determine whether useful net savings exist. B: test longer scored continuations and Large-first transition restrictions with fresh held-out evidence. C: use supported timing/quality constraints to compare a Large-first adaptive policy with equally constrained fixed/request-level controls. Tune on development traces; evaluate on separate traces. Do not invest in vLLM until measured performance and quality jointly support the next step.


## Frozen prefill pilot protocol

# Predeclared overload-prefill experiment

Hypothesis: queue-triggered Small prefill followed by Large decode improves correct-and-SLO-compliant answers/second at acceptable quality, compared with always Large/Small and a fixed Small-prefill/Large-decode policy.

Primary: existing pinned Gemma 3n E4B, official Large/Small presets, bfloat16, one PACE L40S, current eager HF implementation. No training or new model weights.

Workload: 200 deterministically selected SQuAD 1.1 development questions; development calibration uses 32 training examples. Half of the constructed prompts approach 256 tokens, half 1024. Two fixed demonstration QA pairs and irrelevant document filler precede the intact answer-bearing passage. Selection excludes passages too long to fit the chosen bucket, without looking at model answers. Greedy answers stop at the first newline/EOS or 32 tokens. This is a constructed generative workload, not the official SQuAD benchmark.

Policies: Large/Large; Small/Small; Small/Large; adaptive prefill with Large decode. Adaptive selects Small if at least four requests wait or the oldest wait is >=250 ms. All four use the same explicit final-prompt-token boundary: prefix at prefill capacity, last prompt token at decode capacity, then answer decoding. Old prefix KV is retained.

Execution: real wall-clock GPU replay, FIFO within length buckets, oldest queued request selects the next bucket, batch cap 8, batching delay at most 10 ms from the oldest arrival, cohort fully decoded before next cohort. No concurrent GPU operations or continuous admission during decode. This intentionally differs from continuous batching; conclusions apply to this harness. Host scheduling/tokenization-output overhead is included in the wall-clock result. Batch members that finish early remain in tensor execution until the cohort finishes, but their request completion and SLO timestamps end at their own stopping token.

Calibration: development-only saturated batches at each length bucket establish lambda0 = completed requests / elapsed wall time. Freeze rates thereafter. Three seeds (11,22,33), 120 requests each, six alternating 20-arrival light/burst segments, Poisson interarrival times at 0.5/1.25 lambda0. Saved trace identical across policies; policy order randomized per seed. Queue drain is included. Check observed backlog and adaptive activation rather than assuming rates caused overload.

SLO: TTFT <=1000 ms and maximum observed inter-token gap <=200 ms. For one-token answers, no inter-token gap exists and its value is 0. First-answer-token timestamp includes prefix and transition-boundary computation. A correct request satisfies normalized exact match to any reference. F1 is supporting evidence. Main goodput = number of correct requests satisfying both SLOs / full replay wall time. Raw throughput and latency-only goodput reported separately.

Quality tolerance: <=5 percentage points EM loss versus Large. Paired bootstrap uncertainty, accounting for repeated examples by aggregating per example, is reported. If the upper interval bound exceeds 5 points, quality noninferiority is not established. Use paired article-cluster resampling to account for article-level dependence; repeated examples across traces are averaged before resampling.

Adaptive GO: quality gate passes; >=10% goodput improvement over both Large and Small, gains in at least 2/3 traces; plus >=5% goodput over fixed hybrid OR >=3 points better accuracy while retaining >=95% fixed-hybrid goodput. A zero-goodput baseline has no finite percentage ratio; report absolute gains instead and qualify the criterion.

Fixed-hybrid GO: acceptable quality and >=10% goodput improvement over Large; adaptive adds insufficient value. NO-GO in tested setup if neither hybrid passes useful goodput/quality gates. INCONCLUSIVE if quality uncertainty too broad, useful overload absent, or trace variability prevents a reliable interpretation. These are bounded pilot gates, not proof about optimized serving.

Artifacts: code/run_experiment.py; code/presets.json; code/run_pace.sbatch; data/workload.json; results/quality_*.json; results/trace_*.json; results/replay_*.json; results/experiment.json; execution log; analysis and report. No GitHub push.


## Frozen decode pilot protocol

# Decode-policy extension

Added at the user’s explicit request to preserve the original research direction. This is separate from the completed prefill-only pilot.

Same frozen Gemma checkpoint/presets, 200 QA examples, three 120-request light/burst traces, GPU/runtime, admission/batching rules, 1-second TTFT and 200-ms max inter-token SLO. Calibration and traces are reused without retuning. Fixed baselines are rerun in the new job. This remains a real cohort GPU replay, not continuous batching or vLLM.

Compare fixed Large, fixed Small, request-level selection and iteration-level selection. Request-level chooses Small at admission if waiting count >=4 or oldest wait >=250 ms; otherwise Large, then holds that configuration. Iteration-level starts identically (same chosen prefill/initial decode width), then re-evaluates observed waiting requests before each subsequent decode step. It sees only arrivals whose timestamps have passed, not future arrivals or true remaining answer lengths. Width applies to the whole current cohort; KV history is retained. Short completed answers stop their width history even if the cohort continues. Record actual token width histories and switches.

Scored transition diagnostics: fixed Large/Small, Large→Small after two predicted tokens, Small→Large after two predicted tokens, and alternating every two predicted tokens. Same examples and greedy answer scoring. Report the number that actually reach a switch; answers ending before a boundary do not demonstrate transition quality. These schedules are diagnostics, not the adaptive policy itself. A transition changes future predictions, not old cached history.

Quality gate: at most five percentage points EM loss versus Large, with paired article-cluster bootstrap uncertainty. Pilot GO for iteration-level integration requires >=10% correct-and-SLO-compliant goodput over request-level and both fixed baselines, gains in >=2/3 traces, and quality gate pass. Require actual switching in >=10% of iteration-policy requests to claim the transition policy was substantially exercised; otherwise inconclusive. These are provisional screening criteria. Single GPU replay per policy/seed does not establish statistical significance.

If request-level works but iteration-level adds little, prefer the simpler policy. If no policy improves Large meaningfully, do not build vLLM yet. Keep the prefill-only result separate; no unplanned threshold tuning to rescue either result.
