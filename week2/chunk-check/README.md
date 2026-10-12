# Final chunk comparison

Protocol fixed October 10, 2026, before GPU outcomes. Upstream serving code is pinned
to `96e8f1097d2f0be6a513eede6cda04330824da71` on `mixed-serving` and is unmodified.

One L40S job, one resident model, 150 requests from `azure_conv_steady`, rate scale
0.1, three repetitions each of four configurations, rotating order by repetition:

| Configuration | Prefill | Decode |
|---|---|---|
| Large original | Large, existing 2,048-token budget | Large |
| Hybrid original | Small, existing 2,048-token budget | Large |
| Large chunk512 | Large, at most 512 tokens per forward | Large |
| Hybrid chunk512 | Small, at most 512 tokens per forward | Large |

Other scheduling caps and the SLO stay matched: maximum 48 running requests,
batch-1 prefill, decode cap 64, first token at most 1 second, maximum token gap
200 ms. Repetitions retain all stalls. Primary interpretation uses raw deadline
attainment and latency-only on-time requests/second, plus throughput and TTFT.
There is no adaptive controller, quality evaluation, or workload expansion.

Before timing, the upstream full gates and four long-context token-equivalence
checks must pass. The latter compare batched against per-row execution for each
tested schedule, at prompt lengths 700/2,300 and eight generated tokens. These
check execution correctness, not task quality or equivalence across chunk sizes.

`run_check.py` uses the original executor and loop, resets per-run reporting
counters, and saves every request, iteration, and generated token. All inference,
cache rebuilds, and width switching remain inside real serving wall time.
Model/cache loading, correctness gates, and short warmups are outside workload
timing. This remains the teammate's eager padded-cache harness, not production
serving throughput.

The upstream source and exact workload are retained in `source_snapshot.tar.gz`;
file hashes are in `source_manifest.json`. To reproduce, extract the snapshot into
an empty repository directory, place this folder at `week2/chunk-check`, activate
the matching Gemma/PyTorch environment and cached checkpoint, and run:

```sh
python week2/chunk-check/code/run_check.py --out week2/chunk-check/results/reproduction.json
python week2/chunk-check/code/analyze.py week2/chunk-check/results/reproduction.json --out week2/chunk-check/results/analysis
```

PACE allocation: job 6156343, one L40S, four CPUs, 64 GB host memory, 90-minute
limit. The launcher uses the previously established offline checkpoint and venv.

Completed results and interpretation: [REPORT.md](REPORT.md).
