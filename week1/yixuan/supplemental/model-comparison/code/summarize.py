"""Summarize raw decision screens without asserting statistical significance."""

import json
from pathlib import Path

root = Path(__file__).resolve().parent.parent
summary = {}
for name in ["nanochat", "gemma"]:
    p = root / "results" / f"{name}.json"
    if not p.exists():
        continue
    r = json.loads(p.read_text())
    q = {}
    for x in r["quality"]:
        q.setdefault(x["mode"], []).append(x["correct"])
    q = {
        m: {"correct": sum(v), "total": len(v), "accuracy": sum(v) / len(v)}
        for m, v in q.items()
    }
    rows = r["timing"]
    large = "XL" if name == "nanochat" else "large"
    small = "S" if name == "nanochat" else "small"
    cells = []
    for l in rows:
        if l["mode"] != large:
            continue
        entry = {
            "batch": l["batch"],
            "context": l["context"],
            "large_decode_ms": l["decode_ms"],
            "large_prefill_ms": l["prefill_ms"],
        }
        for mode in [small, "compact_small"]:
            v = next(
                (
                    x
                    for x in rows
                    if x["mode"] == mode
                    and x["batch"] == l["batch"]
                    and x["context"] == l["context"]
                ),
                None,
            )
            if v:
                key = "dynamic_small" if mode == small else mode
                entry[key] = {
                    "decode_ms": v["decode_ms"],
                    "prefill_ms": v["prefill_ms"],
                    "decode_saving_percent": 100
                    * (1 - v["decode_ms"] / l["decode_ms"]),
                    "prefill_saving_percent": 100
                    * (1 - v["prefill_ms"] / l["prefill_ms"]),
                }
        cells.append(entry)
    summary[name] = {
        "completed": r.get("completed", False),
        "quality": q,
        "timing_cells": cells,
        "compact_small_max_logit_diff": r.get("compact_small_max_logit_diff"),
        "switches": r.get("switches", []),
    }
(root / "results" / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
print(json.dumps(summary, indent=2))
