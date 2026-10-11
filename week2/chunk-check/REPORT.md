# Final serving check

PACE job **6156343** completed successfully in **66 minutes** on one L40S. Twelve GPU replays: four configurations, three repetitions, 150 requests each. All correctness/accounting gates passed. All requests completed and all stalls were retained.

| Configuration | Requests meeting deadlines, mean | On-time requests/s, mean |
|---|---:|---:|
| Large throughout, original scheduling | 50.9% | 0.251 |
| Small prefill / Large decode, original scheduling | 67.1% | 0.319 |
| Large throughout, 512-token prefill chunks | **88.2%** | **0.428** |
| Small prefill / Large decode, 512-token chunks | 88.4% | 0.427 |

Deadlines: first token within 1 second and longest token gap at most 200 ms.

**Chunking improved Large by 37.3 percentage points**, with improvements in every repetition. Shorter prompt-processing pieces let existing requests receive their next tokens sooner. The tradeoff: mean across runs of median first-token latency rose from 114.5 to 237.6 ms.

**Narrowing added no repeatable advantage after chunking.** The difference was one extra passing request across 450 replayed requests, or 0.22 percentage points. Mean on-time requests/s was slightly lower. Differences across repetitions were -18.7, +24.0 and -4.7 percentage points, so variation is substantial and exact equivalence is not established.

Fixed Small-prefill/Large-decode improved the original scheduler by 16.2 percentage points. That benefit does not establish an advantage over the stronger chunked Large baseline. Total throughput remained about 0.49 requests/s: this low-load replay is arrival-limited and does not measure maximum capacity.

**Recommendation: stop investing in iteration-level width adaptation for this Gemma 3n setup.** Combined with earlier weak decode speedups and missing quality certification, this run supplies no convincing reason for another week of controller experiments. Ordinary scheduling captures the larger observed benefit.

This is a resource decision, not proof that adaptive width never works. No iteration-adaptive controller was tested here. Scope: one low-load Azure trace, synthetic prompt content and prescribed output lengths, one GPU, and the existing eager padded-cache harness. Answer quality was not scored. Generated-token changes are diagnostics, not evidence of quality losses. These results do not establish high-load capacity or generalize to every model/runtime.

Evidence: [per-run results](results/analysis/RESULTS.md), [metrics](results/analysis/runs.csv), [paired comparisons](results/analysis/paired.csv), [audit](results/analysis/audit.json), and [protocol/reproduction](README.md). Compressed raw requests, iterations and generated tokens, the job log, package metadata, Slurm status, and source snapshot are retained in this folder.
