# Week 8 scaled serving

**Status:** complete. The serving-qualification thread closed the sustained-rate
search (P2B), ran two controlled-burst cut tests (P2C, P3C) and an independent
admission replication (P3D). The one-way 8k→4k cut is **not advanced**; the
queue-aware admission rule is the best candidate but is **not confirmed**.

**Result in one line:** more thinking buys AIME accuracy (4k→8k +18.8 points on
96 responses, +14.6 under burst), but the rig's capacity is a cliff rather than
a tunable miss band, and the in-flight cut does not beat admission-only on
correct-on-time.

## Key results

| Result | Evidence |
|---|---|
| AIME carries the 4k→8k slope | +17.2 points over 87 historical pairs; +18.8 over 96 AIME 2025+2026 responses (p = 5.3e-4); +14.6 under P2C burst |
| No 15–40% sustained-miss band at 240 s | 0–1.1% through 1000/h; 95.9% at 1025/h; 56.2% at 1050/h |
| Admission-only is the best point estimate | P2C 41.7%, P3C 45.0%, P3D 38.9% correct-on-time; but the P3D interval over fixed4k includes zero (+2.8, CI [−3.3, +9.4]) |
| The cut is not a goodput win | P2C live −2.5 vs arrival; P3C live4k +0.6 and live6k −1.1, with 6–16 cohort accuracy points lost |
| Full thinking is accurate but late | fixed8k +14.6 accuracy over fixed4k, but only 69.6% on-time in P2C and 76.7% in P3C |

## Start here

| Document | What it answers |
|---|---|
| [reports/CONSOLIDATED-FINDINGS.md](reports/CONSOLIDATED-FINDINGS.md) | One-page verdict, cycle history, what is established, and the record map |
| [reports/P2C-RESULT.md](reports/P2C-RESULT.md) | Quality-first burst pilot: pre-declared design, results, decision `inconclusive` |
| [reports/P3C-PREFILL-RESULT.md](reports/P3C-PREFILL-RESULT.md) | Prefilled-cohort cut stress: pre-declared design and result; the cut's best natural case still ties admission |
| [reports/P3D-ADMISSION-RESULT.md](reports/P3D-ADMISSION-RESULT.md) | Independent admission replication: pre-declared design and result; direction repeats, magnitude does not |
| [reports/P2B-CALIBRATION-STOP.md](reports/P2B-CALIBRATION-STOP.md) | Preview authorisation and the 240 s calibration stop |
| [reports/SLOPE-ANALYSIS.md](reports/SLOPE-ANALYSIS.md) | Why the budget slope is family-dependent, and every AIME pool measurement |
| [reports/POOL-DECISION.md](reports/POOL-DECISION.md) | The AIME 2025+2026 pool, its power limits, and why Omni-MATH was dropped |

## What is decided

1. **Pool.** `aime-2025-2026-v1`: AIME 2026 (30 items, `fresh`) + AIME 2025
   (30 items, `exposed`), all integer-answer, self-gradable and context-safe.
   48 items were measured in the preview; 12 are held out.
2. **Rig.** Frozen week 7 package: vLLM 0.11.2, Qwen3-4B rev `1cfa9a72...`,
   32 slots, 8,192 batched tokens, 12,288 window, eager, no prefix caching,
   legacy contract with a 2,048-token answer allowance.
3. **Answer space held constant** at the legacy 2,048-token allowance, so arm
   differences stay comparable with P1 and P2A. Pool filtering is not applied;
   it remains an open option with an explicit trigger (8k caps above 20%).
4. **Power.** 60 questions × 4 seeds give an 80% MDE of roughly 10–13 points at
   ICC 0.2–0.6. The screening cycles (P2C 240/arm, P3C/P3D 180/arm) have
   MDEs of roughly 10–16 points. None supports a 3–5-point claim.
5. **Closed policy.** The current one-way 8k→4k cut is not advanced. Admission
   needs a powered multi-trace replication before it is called confirmed. A
   value/deadline-aware cut remains the only untested cut hypothesis.

## Repository layout

| Path | Contents |
|---|---|
| `configs/` | Frozen configs: `qualify_aime_v1.json`, `pool_aime_2025_2026.json`, `p2c_burst_pilot.json`, `p3c_prefill.json`, `p3c_live6k_fixed.json`, `p3d_admission.json`, plus the historical Omni-MATH configs |
| `artifacts/` | Candidate `cohort.json` / `questions.jsonl`, hashed traces, and source locks |
| `artifacts/traces-candidates/` | Preview, second-seed, calibration, P2C burst and P3C prefilled-cohort traces with manifests |
| `code/larb_week8/` | Pool, traces, preview/calibration analysis, decision, GPU runner, transition check, `pilot.py` (P2C), `prefill.py` (P3C). Imports the frozen week 7 code. |
| `code/tools/` | Pool/trace builders, slope analysis, candidate stage runner, CPU test driver |
| `code/tests/` | CPU end-to-end tests for preview, calibration, live, P2C and P3C plumbing |
| `results/` | Run outputs (gitignored): `p2a/`, `p2b/`, `p2c/`, `p3c/`, `p3d/` and generated decisions |
| `reports/` | Curated findings: `CONSOLIDATED-FINDINGS.md`, per-cycle results, pool and slope analysis |
| `sbatch/` | Batch and in-allocation scripts; they never submit themselves |

Generated summaries inside `results/` (`PILOT.md`, `PREFILL.md`,
`CALIBRATION.md`) are the authoritative per-run tables and decisions.

## Running the code

The code expects the Week 7 package to be present in the same checkout. Set the
paths for your environment; `PY` runs serving code and `APY` runs analysis code
(the latter needs `math_verify`).

```sh
export ROOT=/path/to/LARB
export WEEK8=$ROOT/week8/scaled-serving
export PYTHONPATH=$WEEK8/code:$ROOT/week7/scaled-serving/code
export PY=${PY:-python3}    # serving environment
export APY=${APY:-python3}  # analysis environment with math_verify

bash $WEEK8/code/tools/run_cpu_all.sh          # pool, traces, audit, pre-calibration, tests
$APY -m unittest discover -s $WEEK8/code/tests -p 'test_*.py'

# P2C: build traces, plan, run on GPU, analyse
$APY -m larb_week8.pilot --stage build --which both
$APY -m larb_week8.pilot --stage plan --which both
$PY  -m larb_week8.pilot --stage run --which a --out $WEEK8/results/p2c/pilot
$APY -m larb_week8.pilot --stage analyse --out $WEEK8/results/p2c/pilot

# P3C: prefilled-cohort cut stress
$APY -m larb_week8.prefill --stage build
$APY -m larb_week8.prefill --stage plan
$PY  -m larb_week8.prefill --stage run --out $WEEK8/results/p3c/prefill
$APY -m larb_week8.prefill --stage analyse --out $WEEK8/results/p3c/prefill
```

`run` refuses to start without `SLURM_JOB_ID` unless `LARB_ALLOW_NO_SLURM=1` is
set. `analyse` is CPU-only but needs the analysis environment for `math_verify`.
See [code/README.md](code/README.md) for the module-level map.

## Limits to carry into the write-up

- One model (Qwen3-4B), one H100, one block; no 3-point claim.
- 30 of the 60 items are `exposed` (AIME 2025) and 30 are `fresh` (AIME 2026);
  report the halves separately.
- 12 items were never used in the preview; report them as the unseen subset.
- The burst and prefilled-cohort traces are controlled load shapes, not
  representative service loads.
- Capped, late, missing or unparseable responses stay in the denominator.
- Cut counts use `worker.jsonl`; the frozen controller can leave a request
  record's cut list empty.

