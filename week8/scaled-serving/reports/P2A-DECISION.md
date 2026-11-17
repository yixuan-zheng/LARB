# P2A decision record

**Run:** Slurm interactive allocation `7119809` (`ice-gpu`, 1 x H100 80 GB),
2026-11-16 20:15-20:29 EST = 2026-11-17 01:15-01:29 UTC.
**Pool:** `omni-math-hard-v1`. **Source lock:** `artifacts/source-lock-p2a.json`.
**Decision:** **STOP** — P2 not authorised; no frozen P2 packet.

## Preview (24 items, one seed, 4k/6k/8k)

| metric | value |
|---|---:|
| 4k / 6k / 8k accuracy | 0.333 (8/24) / 0.292 (7/24) / 0.292 (7/24) |
| 4k→8k gain | **-4.2 points** (floor +8.0; near-miss floor +4.0) |
| answer change 4k→8k | 0.625 |
| 8k cap rate / missing box | 0.042 / 0.042 |
| 8k thinking median | 8192 (22/24 cues at exactly 8192) |
| coverage / grader | 72/72 scored, 0 errors, grader ok |
| decision | **stop** |

Grader robustness on the same records (4k/6k/8k): safe 8/7/7, loose
Math-Verify 8/8/8, exact normalised 8/7/7, raw 10/8/9. The 8k arm never beats
4k, so the stop does not depend on the grading rule.

The 48-item escalation was not triggered: the decision is a stop, not a
near-miss.

## Calibration and live check

Not run. `configs/qualify.json` freezes "gain below 5 points, accuracy_8k below
0.30 ... → documented stop; do not calibrate or run P2". The 240 s calibration,
the refinement round and the live manipulation check therefore remain
unvalidated on GPU.

## P2 packet

- P2 authorised: **no**
- `configs/p2_main_frozen.json`: absent
- Main traces (`low`/`sustained`/`burst`): not built

## Open items / limitations

- One seed, 24 items: the preview resolves only a large slope. The stop means
  this pool does not show the slope, not that the hypothesis is false.
- All Omni-MATH items are `exposed`; no fresh-data claim is supported.
- The 240 s calibration band and the live cut mechanism still need a GPU test
  on a pool that passes a preview.
- **Follow-up (same allocation):** [SLOPE-ANALYSIS.md](SLOPE-ANALYSIS.md)
  attributes the flat result to pool family, and the pre-declared AIME
  2025+2026 candidate reached +8.3 points on the 24-item gate (inconclusive:
  20.8% answer caps) and +18.8 points at 48 items on two independent seeds
  (96 responses, p = 5.3e-4). Re-measuring the same 24 questions inside the
  48-item traces reproduced 0 of 48 token sequences and lifted their gain to
  +20.8/+25.0, so the single-wave 24-item gate systematically understates the
  8k arm. That candidate, not Omni-MATH, is the live thread.



## Reproduction

```sh
bash week8/scaled-serving/code/tools/run_cpu_all.sh
srun --jobid=<allocation> --overlap bash week8/scaled-serving/sbatch/p2a_inallocation_preview.sh
```

Records: `results/p2a/STOP.md`, `results/p2a/decision.json`,
`results/p2a/preview-24.json`, `results/p2a/PREVIEW-24.md`,
`results/p2a/smoke/smoke.json`, `results/p2a/preview/`.
