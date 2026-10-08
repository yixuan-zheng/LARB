# Week 2 workstream A: mixed prefill+decode goodput / SLO harness

**Question this harness exists to answer.** Under a realistic mixed prefill+decode
workload at a fixed latency SLO, does a width policy — the single-switch phase hybrid
(Small prefill → Large decode) in particular — improve **SLO-compliant goodput** over
tuned static Large and static Small, and in which regime?

It is a *harness*: it produces the raw per-request and per-iteration evidence a
comparison needs. Evaluation, analysis and plotting are deliberately separate later
steps, and the load-driven policy is workstream C's, not this one's.

## What is here

| Path | Role |
|---|---|
| `code/serving_core.py` | torch-free engine: clocks, admission, budgets, batching, padding, plans, the shared loop, per-request state |
| `code/serving_lib.py` | the measured executor: real Gemma 3n forwards on one GPU, width application via Week 1's `SwitchController`, batched padded decode |
| `code/cost_table.py` | the replay executor: the *same* scheduler on a measured cost table (a cross-check, never evidence) |
| `code/policies.py` | `static_large`, `static_small`, `phase_hybrid`, plus the workstream-C placeholder and the chunked-prefill lever hook |
| `code/slo.py` | the SLO contract, per-request classification, goodput/attainment reporting |
| `code/workload.py` | trace ingest, deterministic window selection, Poisson/Gamma synthetic controls, rate scaling |
| `code/fetch_trace.py` | one-time download of the Azure trace CSVs into `traces/raw/` (git-ignored) |
| `code/calibrate.py` | cost table: seeded from frozen Week 1 results, or measured through the loop's own forwards; plus the capacity/load-ladder report |
| `code/validate_harness.py` | the gate suite (accounting, dynamic≡static, batched≡per-row, injected delay, null control) |
| `code/run_serving.py` | the runner: interleaved policies × repetitions, crash-safe records, flat CSVs |
| `code/test_serving_cpu.py` | 89 CPU-only checks of the stdlib half (login node, seconds) |
| `code/smoke_cpu_model.py` | **model-backed correctness check on CPU**: padded batched decode must equal the per-row reference *and* a one-shot greedy continuation |
| `code/run_pace.sbatch` / `code/run_cpu.sbatch` | PACE launchers (GPU: validate/calibrate/serve; CPU: smoke/unit/seed/replay) |
| `traces/` | committed normalized windows + synthetic controls + `manifest.json` |
| `results/contract.json` | **the frozen SLO / regime / goodput contract** (do not retune after seeing results) |
| `results/costs/` | seed cost table + `capacity.json` (the measured load ladder) |

## The design in six points

### Facts about this checkpoint the harness has to respect (measured, not assumed)

Found and fixed while building — each one would have silently corrupted every latency
number if it had been left as an assumption:

* **Gemma 3n E4B has 35 text layers but only 20 own a KV cache** (the rest share it).
  That is also why Week 1 measured exactly 40,960 B/token (2 × 2 KV heads × 256 dim ×
  2 bytes × 20 layers). The harness learns the count from the cache the model returns.
* **The cache tensor layout is `[batch, heads, sequence, head_dim]`** — the sequence
  axis is `-2`, not `1`. Every cache helper indexes through `-2` so this cannot be
  silently mis-sliced again.
* **The cache object carries per-layer attention flags** (Gemma 3n mixes sliding-window
  and global attention). A cache rebuilt from tensors alone tells the model every layer
  is global and changes the logits; the harness therefore keeps each request's real
  cache object and, when it must rebuild one, copies the layer objects so the flags
  survive. Measured: a self-built cache produced a different second token for a 24-token
  prompt, and the template-preserving rebuild reproduces the stock path exactly.
* **A 2-D `attention_mask` cannot be used for a padded batch** with mixed sliding/global
  layers (HF sizes the mask itself and rejects it). The harness builds the two 4-D
  additive masks explicitly, for `full_attention` and `sliding_attention`, and passes
  them as the mapping HF expects.

1. **One model, three configurations.** Every configuration runs the same resident
   switchable full-weight E4B model and differs only in the width plan it applies.
   Model build, load order, VRAM and dynamic-path overhead are therefore identical
   across configurations, and Week 1's S8 gate (`dynamic-at-W` logits `==` static-W,
   `max_abs_logit 0.0`) is the justification for calling them static Large/Small.
2. **One width per batch per iteration.** The scheduler returns one width for the
   prefill batch and one for the decode batch, so an iteration performs at most one
   switch: the phase hybrid's prefill/decode boundary switch. Mixed-width batches are
   unsupported by the mechanism and are never proposed.
3. **Prefill is batch-1** — the only supported path. Measured here: a 2048-token prefill
   costs 160.1 ms at batch 1 and 811.0 ms at batch 4 (8192 tokens) — 12.8k vs 10.1k
   prompt tokens/s, so batching prefill is *slower per token* in this runtime. Padding a
   prefill batch would also need per-query masks for the mixed attention, so
   `prefill_batch_cap > 1` is a loud `NotImplementedError` rather than a slower,
   riskier path.
4. **Decode is batched**, because decode step time is flat in batch (54.9 ms at batch
   1, 74.1 ms at batch 64/context 2048), which is where the throughput is. Batched
   decode needs a common cache length, so each iteration left-pads the rows' caches to
   the batch maximum, hides the pad slots with the explicit masks above and passes
   **per-row `position_ids`** (Gemma3n's default is `arange(q_len) + past_seen_tokens`,
   which is only correct for uniform rows). The rebuild is *measured* and charged per
   iteration (`cache_rebuild_ms`); a production paged-attention server would not pay it,
   so absolute throughput here is conservative.
5. **The workload is a real trace.** Windows of the Azure LLM inference trace 2023
   (CC-BY) with a real burst structure and a real prefill/decode mix, plus synthetic
   Poisson/Gamma controls that are reproducible without the source CSV. Load is swept
   with `--rate-scale` (time compression), and the ladder is derived from the measured
   capacity *before* any policy comparison.
6. **Nothing measured is mixed with anything simulated.** Every record carries
   `mode: measured | replay`; replay output exists to validate the scheduler on CPU
   and to cross-check the measured loop, and never stands alone as evidence.

## The contract (frozen; full text and sources in `results/contract.json`)

* Primary gate per request: **TTFT ≤ 1.0 s AND max ITL ≤ 200 ms**; secondary:
  mean TPOT ≤ 100 ms; TTFT-only attainment is always reported alongside. Sensitivity
  grid: TTFT {0.5, 1.0, 2.0} s × max-ITL {100, 200} ms.
* One line of rationale each: unloaded TTFT is 113–135 ms at batch 1 and 738–840 ms
  for a batch-8 × 1024 prefill, so 1.0 s is achievable when unsaturated and violated
  only under interference (and it is the Week 1 pilot's value, keeping the two weeks
  comparable); measured decode ITL is 53.6–57.3 ms and width-independent, so the ITL
  gate is a fairness guard that fires when prefill work is packed into an iteration
  (a 2048-token prefill is ~160 ms of GPU before the ~55 ms decode step) — bracketed by
  Sarathi-Serve's 5×/25× decode-step rule (275 ms / 1.4 s here) and DistServe's 0.1 s TPOT.
* `goodput = completed ∧ quality-eligible ∧ SLO-satisfying requests / wall time`,
  reported over both the trace window and a warm-up-free evaluation window, with the
  non-attainment breakdown (TTFT-only / ITL-only / both / incomplete).
* The quality floor is **imported** from `week1/quality`; the harness records each
  request's exact per-step width history so the quality layer can score the schedule
  that actually ran, and applies no online penalty. The phase hybrid's history is
  exactly the `SL_early` schedule already scored at −1.6 pp on GSM8K dev.

### The load ladder, derived before any comparison

`code/calibrate.py --mode seed` turns the frozen Week 1 cells into a cost table and
computes capacity from them. For the `azure_conv_steady` window (mean prompt 1,117
tokens, mean output 249, mean rate 5.50 req/s) the seeded estimate is **3.24 req/s**
of service capacity, split **28% prefill / 72% decode** of GPU seconds, giving
`--rate-scale` values of **0.30 underloaded / 0.53 saturated / 0.77 overloaded /
1.18 backlog-inducing** on that trace. Those numbers are the *starting* ladder: the
measured table from `--mode measure` replaces the seed and the ladder is recomputed
once, before any policy comparison, and never tuned afterwards.

## Reproduce

```bash
# 0) environment (frozen Week 1 venv + HF cache; also sets PYTHONPATH)
source week1/latency-baselines/env.sh

# 1) CPU-only logic checks, seconds, no GPU, no model
python week2/mixed-serving/code/test_serving_cpu.py

# 2) traces (once; everything afterwards is offline)
python week2/mixed-serving/code/fetch_trace.py
python week2/mixed-serving/code/workload.py azure-windows --out week2/mixed-serving/traces

# 3) seed cost table + capacity/load ladder from the frozen Week 1 results
python week2/mixed-serving/code/calibrate.py --mode seed \
  --trace week2/mixed-serving/traces/azure_conv_steady.json

# 4) a simulated smoke of the whole loop (no GPU): 3 policies on one window
python week2/mixed-serving/code/run_serving.py --mode replay \
  --cost-table week2/mixed-serving/results/costs/cost_table_seed.json \
  --trace week2/mixed-serving/traces/synth_poisson.json --rate-scale 0.3 \
  --gates none --force --tag smoke

# 5) the model-backed correctness check (CPU; a few minutes on 8 cores)
sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=smoke_cpu \
  week2/mixed-serving/code/run_cpu.sbatch

# 6) GPU: gates, the cost table measured through the loop, then runs
sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=validate \
  week2/mixed-serving/code/run_pace.sbatch
sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=calibrate \
  week2/mixed-serving/code/run_pace.sbatch
sbatch --export=ALL,STUDY_ROOT=$PWD/week2/mixed-serving,STUDY_MODE=serve \
  week2/mixed-serving/code/run_pace.sbatch -- \
  --trace traces/azure_conv_burst.json --rate-scale 1.0 --reps 3
```

## Gates before results (`code/validate_harness.py`)

| Gate | Question | Pass condition |
|---|---|---|
| `accounting` | does the loop's own bookkeeping add up? | timestamps, widths, token counts, prefill positions and per-iteration sums exact |
| `switchable_equals_static` | is the dynamic path the static path? | `max_abs_logit == 0.0` per preset (Week 1's S8 check, re-run inside the loop) |
| `batch_equivalence` | does padded batched decode equal per-row decode? | identical token ids |
| `injected_delay` | can the meter see a known delay? | median max-ITL moves by about the injected amount |
| `null_diff` | how much does the harness move on its own? | identical schedules; the spread is reported as this machine's noise floor |

`run_serving.py --mode measured` runs the suite first and refuses to write results
unless it passes (`--force` stamps every artifact `gates: failed_forced`).

## Blind spots of the earlier efforts, and how they are covered here

* **Never overloaded** (the Week 1 pilot's cohort-FIFO never produced a backlog):
  admission is continuous FIFO, and overload is defined before the run — the fraction
  of iterations beginning with an unstarted queue or an undecoded backlog above 0.5,
  plus TTFT p50 above twice the unloaded value. Both signals are reported per iteration.
* **Prefill share ≈ 0** (the pilot's answers averaged ~5 tokens): the workload's prompt
  is 1,020 tokens at the median and the output 129, so prefill is a real share of
  steady-state work — 28% of GPU seconds per request in the seeded capacity estimate.
* **Mixed widths billed as serialization**: one width per batch is enforced and the
  batch composition is reported, so that artifact is visible instead of implicit.
* **Future knowledge**: the policy sees an explicit `EngineView` with no output-length
  field, enforced by construction and covered by a test.
* **One replay per policy, no uncertainty**: repetitions are interleaved in a rotating
  order, and the harness's own spread is measured by the `null_diff` gate.
* **Quality not enforced online**: the per-step width history is recorded for later
  scoring; no penalty is invented.

## Deliberately out of scope here

A continuous-batching runtime, vLLM integration, the load-driven policy (workstream C),
quality scoring of the new runs (workstream B / future), and all analysis and plotting.
The chunked-prefill lever exists (`--prefill-chunk`) and stays lower priority: it is
exercised by the CPU checks and one sanity configuration, with no conclusions drawn.

## Evidence committed alongside the code

| Artifact | What it shows |
|---|---|
| `results/test_serving_cpu.json` | 89 CPU checks of the scheduler, budget, padding, SLO accounting and replay paths, including the known-effect and null controls |
| `results/smoke_cpu_model.json` | the **real model on CPU**: `single_row` *and* padded `batched` decode each reproduce a plain one-shot greedy continuation token for token, for both width schedules (`static_large` all-large, `phase_hybrid` `SL_early`), and batched equals per-row |
| `results/costs/cost_table_seed.json` | cost table seeded from the frozen Week 1 / decode-study measurements, with the source file named per cell |
| `results/costs/capacity.json` | measured capacity (3.24 req/s, 28% prefill / 72% decode of GPU seconds for the conv window) and the recommended `--rate-scale` ladder |
| `results/replay-smoke/` | one labeled **simulated** run of all three policies on a 40-request load — a demonstration that the reporting path works, not a result |

What is *not* here yet, and is the next work: measured GPU runs, the gate verdicts from
a real device (`results/gates/job-*.json`), and the cost table measured through the loop
(`results/costs/cost_table_measure.json`). Those need one L40S hour each and are the
first thing to run after this harness landed.


