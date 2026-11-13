# Hidden-state extraction failure report

November 12, 2026 · Decision brief

**The replication has no probe results yet.** The first job stopped at a Python compatibility error. The retry loaded the pinned Qwen3-4B BF16 model and stopped at the first numerical parity comparison. Both attempts ended before bulk extraction.

## What happened

| PACE job | Runtime | Observed result |
|---|---:|---|
| 6996647 | 2m 50s | Release verification called `hashlib.file_digest`, which PACE's Python 3.10.13 lacks. The exception occurred before model load. A streaming SHA-256 replacement passed a CPU test on the same interpreter. [Slurm log](evidence/hidden-state-replication-20261112/slurm-6996647.out) |
| 6997511 | 3m 16s | The corrected release passed verification and loaded all three model shards on an L40S. The first feature comparison, Week 7 `q04-b0` at the prompt-only checkpoint, exceeded the relative L2 limit. The gate stopped immediately. [Slurm log](evidence/hidden-state-replication-20261112-v2/slurm-6997511.out) · [Gate record](evidence/hidden-state-replication-20261112-v2/job-6997511/engineering-gate.json) |

| First comparison | Observed | Frozen criterion |
|---|---:|---:|
| Cosine similarity | 0.999797 | ≥ 0.999, passed |
| Relative L2 error | 2.015073% | ≤ 2.000%, failed by 0.015073 percentage points |

The optimized path forwards the prompt and full 4K reasoning prefix once and slices the final-layer states. The upstream reference forwards only the tokens through each checkpoint. The recorded vectors point in nearly the same direction but differ enough in relative L2 to fail the gate. Different BF16 execution paths at different sequence lengths are a plausible explanation. The run did not isolate sequence length from differences between the two forward entry points and masking. [Extraction code](extract.py) · [Frozen criteria](PROTOCOL.md)

## What remains unknown

Only one of the 36 planned parity comparisons was recorded. This was the final prompt-token control. Parity for the four-token reasoning means, including at 4K, remains unknown. The run exited before recording peak reserved GPU memory or the bulk-throughput projection. There is no feature archive, held-out AUROC, or evidence about continuation-benefit prediction.

## Next-step options

1. **Use direct per-checkpoint forwards for the replication.** This is the closest match to the published extractor. Start with a small timing and memory gate on the three planned trajectories and proceed only if the measured workload fits. The extra forwards raise compute above the single-pass design, so estimate wall time from the gate before relying on the original one-hour request.
2. **Diagnose the single-pass path before using it.** Compare the two forward entry points at identical lengths and masks, then compare direct prefixes against slices across all planned positions. Record the whole diagnostic grid. If the results justify a different numerical criterion, version it before any bulk run and document its effect on the extracted representation.

I recommend **option 1** if the immediate priority is a faithful correctness replication. Option 2 is useful if the direct path proves too expensive. The single prompt-only measurement gives little basis for changing the frozen tolerance. Neither option has been launched.
