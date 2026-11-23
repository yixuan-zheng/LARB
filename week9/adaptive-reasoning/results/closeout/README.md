# Compact evidence archive

- `evidence.json` contains archived policy summaries, validity records, exact scored trace records, and compact per-request outcomes. It also includes both GRPO screens and offline shift/control summaries.
- `earlier.json` preserves earlier math grid and predictor summary artifacts. Older source experiments are indexed in the research narrative.
- `live.csv` and `paired.csv` are regenerated from the evidence by the figure script. Pairing is by question on identical traces. Cross-job comparisons are explicitly labeled.
- `pace-jobs.psv` records completion and failure status, elapsed time, exit code and allocation. A Slurm failure can contain valid completed arms. Eligibility for scoring comes from the arm's timing record.

Raw model outputs, full ingress and worker traces, unpublished full training manifests and optimizer states remain in the PACE directories for the corresponding jobs. Keep raw evidence under the source account or the approved team share. The final replay's frozen questions, routes, seeds and adapter provenance are included under the integration directory. Research-stage launchers outside the portable reference retain historical PACE paths as run provenance. The reference launcher uses explicit environment inputs.

## Schema

The `serving` object in `evidence.json` is keyed by run. Each run provides a PACE `job`, phase `summaries`, `validity` by phase, `scored_rows` by phase, and emitted `traces` by condition. A scored row records the question ID, deadline and completion indicators, correctness, token counts, timing and budget fields where archived. Use `good` for correct on time and `correct` for eventual correctness. `live.csv` records one row per valid arm and block. `paired.csv` pairs questions within an identical trace and labels both source runs for separate allocations. Blank CSV fields denote unavailable metrics. Thresholds and timing definitions are in the [policy contract](../../integration/POLICIES.md) and [reference replay](../../integration/reference/pilot.py).
