# Audit: `week1/latency-baselines`

Audit of the methodology, results and conclusions in this directory, based on the textual
reports (`README.md`, `results/latency_report.md`) plus a full read of the code, configs and
archived results. It was done in **two passes**: a first, compute-free pass (CPU-only:
`analyze_latency.py`, `report_latency.py`, the two test scripts, `py_compile`) that verified the
existing results and fixed the small defects (D1–D4); and a second pass on a compute node (one
L40S) that fixed the remaining flagged defects (D5–D9) and **re-ran the affected scenarios**
(S4, S6, S8, S11) to regenerate the tracked results. Numbers below are read from the (current)
tracked records.

## 1. Reproducibility and gates

* **Pipeline is deterministic and self-consistent.** Re-running `analyze_latency.py` then
  `report_latency.py` reproduces `results/latency_report.md` **byte-for-byte** from the
  git-ignored `run-output/`. The tracked `results/*.json`/`*.csv` therefore really do derive
  from the tracked scenario records; no conclusion-determining number lives only in `run-output/`.
* **Instrument gate (S0) passed.** 3/3 gating checks: `known_2x_compute` = **2.172x** (accepted
  window 1.80–2.40; the >2 direction is itself reported as a real geometric-efficiency effect),
  `null_diff` within noise (ratio 0.991, residual bias **0.90%**, MDD 1.40%), `gemv_scaling`
  R²=0.995 with a fixed overhead of **86.8 µs/call** and an implied **615.9 GB/s = 71.3% of the
  864 GB/s roof**. The L2-flush probe is informational and shows no detectable effect.
* **Dynamic gate (S8) passed.** dynamic-at-W ≡ static-W with `max_abs_logit = 0.0` at large,
  medium and small — and, after D5, in the cached decode path too; the two-identical-conditions
  null control is within noise (ratio 0.9988 decode / 1.0007 prefill). The mechanism is
  numerically exact.
* **CPU test records**: `test_flop_model` 32/32 checks, `test_switch_schedules` 24/24 checks,
  both re-run and reproducing their tracked JSON.

## 2. Verified load-bearing results

| Claim | Evidence | Verdict |
|---|---|---|
| Width change does **nothing** to decode latency | S1/S3 gpu ratio 0.989–0.998 at B∈{1..32}, ctx∈{1,128,2048}; all `within_noise`, MDD ≤0.8% | **supported** |
| Width change **does** help prefill | S2 appreciable in 8/12 grids, best small/large = 0.8235 (**1.214x**, L512_B4), L2048_B1 1.20x; S5 eager 1.216x, compile 1.242x | **supported** |
| Prefill win is bounded by the FFN time share | S6 prefill FFN *time* share (AltUp included) 42.0–50.6% → ceiling **1.136–1.169x**; measured 1.14–1.21x (the 1.169x bound contains S6's own 1.15x large/small ratio) | **supported** |
| Memory saving is exact | FFN 6.56→4.69 GiB and total 13.73→11.86 GiB (large→small); analytic vs measured −0.03% | **supported** |
| Dynamic switching is exact and cheap | equivalence 0.0 (single forward and cached decode); host `apply` **86.2–86.8 µs**; tax/cold/null all `within_noise` | **supported** |
| One switch at the prefill/decode boundary banks the prefill win | S9 capture **0.991 / 0.994 / 1.008** where the win is resolvable; boundary cost ≤0.64 ms | **supported** |
| Per-token alternation is essentially free | S10 `alternate` overhead −0.005…+0.062%; static decode widths themselves unresolvable (\|Δ\|≤0.34 ms) | **supported (see D6)** |

The through-line is coherent: the FFN is 88.6% of *linear-layer FLOPs* but only ~34–42% of
*prefill step time* and ~16–20% of *decode step time* (module shares; AltUp, added in this run, is
the largest single non-FFN block); removing 28.6% of FFN weights therefore moves
prefill (compute-bound) but not decode (launch-bound on a long chain of small kernels, ~26–31%
of DRAM peak and ~0.03% MFU). The `alpha` correction is well documented: S0's 87 µs/call is
*per isolated kernel* and does **not** transfer (S1 shows ~35 µs for a real forward), so the
flat decode ratio is a genuine device-time result, not a host artefact.

## 3. Defects found

### Fixed on the spot

**D1 — S4 ran at the wrong batch size (real bug, results need regeneration).**
`s4_end_to_end.py` built the prompt with `prompts[...].repeat(len(runnable), 1)` while labelling
rows with the configured `batch`. S4 runs one preset per process, so `len(runnable)` is always
1 and **every "B8" row was a batch-1 generation** whose `decode_tok_s`/`e2e_tok_s` were then
multiplied by 8. Corroboration: S4 L128 B1 vs B8 ITL are 54.234 vs 54.202 ms and TTFT 112.84 vs
112.84 ms (identical), whereas S3 measures a real batch-8 L128 step at **55.69 ms**; the two
bugs are the same latent pattern already fixed in S2/S3 ("an earlier version used `len(runnable)`").
Fixed the line (and added a comment) and **re-ran S4 on the compute node**: the B8 rows are now
genuine batch-8 generations (small L128: ITL 54.81 ms vs B1 53.58 ms, e2e tok/s 144.0 vs 18.4),
and `results/latency_report.md` plus both `s4_end_to_end*.csv` files were regenerated. The
*cross-process width ratios* were already unaffected (all presets ran at the same batch), and the
corrected run leaves the verdict unchanged (S4 `within_noise`, ratio 0.984–1.002).

**D2 — stale numbers / mixed GiB-GB units in `README.md`.**
`12.73 GiB` → **13.73 GiB** (12.73 was the pre-`lm_head` total); S7 "7.05 GiB vs 5.03 GiB of
FFN weights" → **6.56 GiB vs 4.69 GiB** (the old figures were decimal GB); "removing 15% of the
weight bytes" → **~14%** (1.88/13.73); S11 "(at +2.01 GiB over small-only)" → **+1.88 GiB**;
`test_flop_model` "31 checks" → **32**; "S0 measured a ~1.4% residual bias" → **~1.4% minimum
detectable difference and a ~0.9% residual bias** (the report's own `residual harness bias`).

**D3 — misleading S11 capacity footnote.** The report said the long-context row is "KV-bound,
not weight-bound". It is neither: S11 keeps the dynamic model **plus** static small **plus**
static medium resident (~38 GiB of 44 GiB), so the batch-8 cap is driven by co-resident weights,
not by FFN width or KV. Reworded the generator note in `report_latency.py` (and, in D8, replaced the
confounded measurement with a per-process one); report regenerated.

**D4 — stale/incorrect docstrings.** `s5_backends.py` claimed "A decode workload is also
measured" (no decode tier exists in the file); `latency_lib.py` and `build_worker.py` still said
dynamic switching is "out of scope" though S8–S11 exist. All three corrected to match the code.

### Fixed on the compute node (D5–D9)

**D5 — S8's equivalence gate never exercised the decode path. FIXED.**
`s8_switch_mechanism.py` now additionally prefills at each width to build a KV cache and compares
the *next-token* logits between the switchable model and the static reference (full width vs the
stock forward); the check is part of the pass/fail gate. Re-ran S8: `max_abs_logit = 0.000e+00` at
large, medium and small with the cache present (rendered as "S8 decode-path equivalence"). The
switchable path is now shown exact on the code path S9/S10 actually switch on.

**D6 — S10 rendered only the `alternate` schedule. FIXED.**
`report_latency.py` now emits a second S10 table listing every switching schedule
(alternate/block1/block4/block16/random) per grid. The worst is **0.43%** (block4, L2048_B8) —
still `within_noise`; the "≤0.06%" headline is the strict per-token `alternate` case, now labelled
as such. (No re-measurement; the data was already in the record.)

**D7 — the fitted decode cost model is not identified. FIXED.**
`report_latency.py` now prints an explicit "**not identified**" caveat (with R²) for any fit with
R²<0.5, so the decode fit (R²=0.045) is no longer read as evidence. The stronger prefill fit
(R²=0.979) is unaffected. (No re-measurement.)

**D8 — S11 could not answer its capacity question. FIXED, and the answer is a clean negative.**
The capacity probe now measures **each option in its own process**, so only one model is ever
resident. (The obvious fix — parking the other models on the CPU — was killed by this allocation's
**16 GiB host-memory cgroup**; process isolation avoids host copies entirely and required
reordering S11 so the models are released before the sub-process probes.) Re-ran S11: at ctx 1
every option reaches the 128 cap; at ctx 2048 every option reaches **32** (not the cap). With the
confound removed, the ~1.9 GiB FFN-width difference **does not move the batch cap** in these
regimes — and the old "8" was purely a co-residency artefact (isolation raised it to 32). The
report footnote and the README sentence were rewritten accordingly.

**D9 — AltUp was missing from the module attribution. FIXED (with an unexpected consequence).**
AltUp is called as `altup.predict`/`altup.correct`, which bypass `forward`, so its forward hooks
never fired. `s6_layer_profile.py` now wraps those two bound methods with the same CUDA-event
timing and sums them back into the `altup` tag. Re-ran S6 for all three presets: AltUp is the
largest single non-FFN block (**~14–17% of the decode step, ~22–26% of prefill**), and the
attributed total rises from ~55% to ~80% of the step.

*Unexpected data, reconciled.* Because the attribution denominator is now larger, the S6 ceilings
fall from 1.214–1.247x to **1.136–1.169x** (prefill), and the FFN step share falls to 34.0–42.1%
(prefill) / 16.4–20.4% (decode). The measured prefill ratios (up to 1.214x at the attention-light
S2 grid L512_B4) now sit *above* this grid's ceiling, so the report's "the ceiling caps every
width win" sentence was corrected to a **per-grid bound**: S6's own large-vs-small prefill step
ratio (1.15x) does sit inside the large preset's 1.169x ceiling, and grids with lighter attention
carry a larger FFN share and hence a higher ceiling. The ceiling keeps the attributed-share
denominator — the one consistent with S6's own measured ratio.

## 4. Conclusions from the experiments

1. **The static width lever is a prefill/throughput lever, not a per-token latency lever.**
   Narrowing the FFN buys ~1.14–1.21x on prefill, bounded per grid by the FFN's share of step
   time (S6 ceiling 1.136–1.169x; S6's own large/small prefill ratio of 1.15x sits inside it),
   and ~1.00x on decode at every batch and context measured.
2. **The memory saving is the certain, arithmetically guaranteed win**: 1.88 GiB off the resident
   set, from a component (embeddings + per-layer embeddings = 5.38 GiB) that no width change can
   touch.
3. **Dynamic switching is a solved mechanism.** It is numerically exact (0.0 logit delta), costs
   ~87 µs of host work for all 35 layers (vs a ~6 s reload), adds no measurable tax (its own
   overhead is within noise, slightly *negative*), and a single prefill→decode switch banks
   0.99–1.01x of the static prefill win at ≤0.6 ms boundary cost.
4. **The honest null result is in decode:** the large-vs-small *decode* widths are themselves
   indistinguishable (|Δ|≤0.34 ms), so "switching costs nothing in decode" strictly means
   "there is nothing to gain or lose there".

## 5. Paths forward for latency-aware scheduling in continuous batching

* **Width as a prefill/TTFT lever.** The one strictly demonstrated policy is the S9 "phase"
  schedule: narrow prefill, one switch, wide decode. It pays off exactly when prefill is a large
  share of a request's end-to-end time: S9 (only 32 decode tokens) shows an **appreciable 4.4%
  e2e** gain at L2048_B4, but as decode grows the same saving shrinks (S4's 96-token generation
  shows a ~1% whole-request small-vs-large difference: 65 ms out of 5464 ms at L1024_B1, most of
  it a slightly faster decode rather than prefill). In a real server, decode
  usually dominates, so the lever is really **TTFT/SLO protection under load**: shrink prefill
  compute so head-of-line TTFT stays inside budget when the batch is congested.
* **Width as a memory/admission lever (the safest use).** One switchable weight set (13.73 GiB)
  replaces two static ones (25.59 GiB) at +1.88 GiB over small-only, and a request's width can
  be changed for ~87 µs. That is a natural primitive for a scheduler that admits/evicts on a
  weight/KV budget: keep the wide model resident, down-shift or up-shift per iteration rather
  than swapping checkpoints. (The capacity payoff is now measured and negative — with one model
  resident at a time the ~1.9 GiB width delta does not move the batch cap; D8.)
* **What a scheduler would need that this suite does not produce:** a measurement where prefill
  is *mixed* with decode (chunked prefill / continuous batching), under a token budget, so the
  win is expressed in **throughput and SLO attainment** (TTFT p99, goodput) rather than in
  isolated-step latency. Recommended next experiments: (i) a chunked-prefill loop that measures
  goodput at fixed SLO with a width policy vs without; (ii) a per-iteration policy that picks
  width from the current batch's prefill:decode token mix; (iii) a quality guardrail, since every
  schedule here changes outputs by construction.

## 6. Limitations — of the approach and of the setup

**The approach (why a prefill saving need not move e2e latency).** The measured win is
per-forward and per-component: even a 25% faster prefill is diluted by (a) the decode-dominated
e2e time (S4: ~1%), (b) the FFN's *time* share, which bounds the prefill win at ~1.17x at the S6
grid (lower where attention is heavier), and (c) the
fixed ~52–55 ms/step decode floor that no width touches. In a continuous-batching server the
dilution is worse still, because prefill can be overlapped with other requests' decode and is a
small fraction of steady-state work.

**Over-representing the speedup.** (1) The best case for width is isolated prefill with a
repeated identical prompt (S2/S5) — a pure GEMM-width experiment with no scheduling, no
overlap, no padding masks, and L2 flushed between iterations. (2) S11's flexibility claim counts
a *host* `apply` against a *full reload*; a real system could keep two models warm, or reload
from host pinned memory far faster than 6 s. (3) The captured prefill win (S9) is measured with
few decode tokens, the regime most favourable to it.

**Under-representing the speedup.** (1) The suite is single-request, eager, with no runtime —
a real server batches, overlaps prefill/decode and could turn the prefill saving into throughput
rather than latency. (2) `alpha` is partly amortized away here but the decode step is still
launch-bound; batching and CUDA graphs (which failed to capture: `cudaErrorStreamCaptureInvalidated`
for all presets, recorded in S5) could change the decode picture, though S1/S3 argue the ceiling
is low regardless. (3) The mechanism holds **one width for the whole batch per iteration**, so
the mixed-width continuous-batch case (different requests wanting different widths in one step)
is unmeasured and unsupported.

**Setup caveats.** (1) All results are one L40S, bf16, one process; the analytic model counts
dense FLOPs and credits the mean/std/relu `gaussian_topk` with no FLOP savings (stated in
`latency_math`). (2) The module attribution (now including AltUp, D9) still covers only ~80% of
the step, so the S6 ceiling rests on the attributed subset. (3) Schedules change model outputs by
construction, so nothing here is a *quality* claim — only a latency-mechanism claim.

## 7. Changes made in this audit

Compute-free pass (earlier): the S4 batch-size fix (D1), the `README.md` number/unit fixes (D2),
and the S11 footnote and scope-docstring fixes (D3, D4).

Compute-node pass (this run):
* `s6_layer_profile.py` — AltUp method-level attribution (D9); re-ran S6 for all presets.
* `s8_switch_mechanism.py` — decode-path equivalence gate (D5); re-ran S8.
* `s11_switch_flexibility.py` — per-process capacity isolation, reordered to free the models first
  (D8); re-ran S11, and raised the documented cap in `run_session.sh` to 128 to match.
* `s4_end_to_end.py` results — re-ran S4 so its data matches the fixed code (D1).
* `report_latency.py` — S8 decode-equivalence rendering, all-schedules S10 table (D6), the fit
  "not identified" caveat (D7), and the grid-scoped ceiling wording (D9 consequence).
* Re-ran `analyze_latency.py` + `report_latency.py`; `results/latency_report.md` and all
  `results/*.csv`/`*.json` regenerated.

All edited files pass `py_compile`; `test_flop_model` (32 checks) and `test_switch_schedules`
(24 checks) re-run green; every scenario is rendered (no coverage gap); the reporting pipeline is
reproducible end-to-end.
