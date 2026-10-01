"""Audit saved request metrics and fair trace replay, independently of GPU execution."""

import json, math
from pathlib import Path

root = Path(__file__).resolve().parent.parent
out = root / "results"
record = json.loads((out / "experiment.json").read_text())
policies = sorted({x["policy"] for x in record["traces"]})
assert record["completed"] and len(record["traces"]) == 12
for seed in [11, 22, 33]:
    expected = {}
    for policy in policies:
        r = json.loads((out / f"replay_{seed}_{policy}.json").read_text())
        rows = r["requests"]
        s = r["summary"]
        assert len(rows) == 120
        ids = {x["id"]: x["arrival_s"] for x in rows}
        assert len(ids) == 120
        if expected:
            assert ids == expected
        else:
            expected = ids
        for x in rows:
            assert x["ttft_ms"] >= 0 and x["max_itl_ms"] >= 0
            assert x["latency_pass"] == (
                x["ttft_ms"] <= 1000 and x["max_itl_ms"] <= 200
            )
            assert x["quality_slo_pass"] == (x["latency_pass"] and bool(x["em"]))
            if "token_widths" in x:
                assert x["switches"] == sum(
                    a != b for a, b in zip(x["token_widths"], x["token_widths"][1:])
                )
        assert math.isclose(
            s["goodput"], sum(x["quality_slo_pass"] for x in rows) / s["wall_seconds"]
        )
print(
    "PASS: 12 policy replays, 1440 request metrics, trace identity, and goodput arithmetic"
)
