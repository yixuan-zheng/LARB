# Reading prior work through its evidence

The [audit report](REPORT.md) examines LASER, Dynasor/Certaindex, P-PAS/P-PAS+, UniBoost and queueing-aware reasoning allocation, with an explicit ACER access gap. It separates reported measurements from our critique and explains how the findings can inform LARB without treating similar ideas as disqualification.

[Source identifiers and hashes](sources.json) record exact inspected versions and visual coverage. [Verification](verification.json) independently recomputes the P-PAS+ comparison from pinned author logs; this is arithmetic verification, not a benchmark rerun. Full papers, external code and logs remain outside the tracked folder.

To reproduce that calculation, download the two public log files marked with `model` in `sources.json` into an external cache, preserving their `cache_filename` values. From the repository root:

```bash
python3 -B week4/literature-audit/verify_artifacts.py --artifact-dir /path/to/external/cache
```

The script checks hashes, successful-run fields, unique seeds, matched arrivals/requested lengths and the paper's condition-level aggregation. It uses only the standard library and never imports upstream code or submits jobs. The Qwen artifact contains ten seeds despite the appendix's eleven-seed description; the actual saved request counts and headline arithmetic still reproduce.

The [earlier LASER CPU/interface report](../laser-feasibility/REPORT.md), [fixed-budget comparison](../baseline-controls/REPORT.md) and [offline diagnosis](../baseline-controls/diagnosis/REPORT.md) provide the local evidence. The controller remains unchanged. A short future note here can record newly accessible sources, resolved numerical questions or independent reproductions without rewriting historical evidence.
