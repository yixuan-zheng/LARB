"""Derive the two frozen burst-only blocks without using outcomes."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
ORDERS = (("arrival", "entry", "live"), ("entry", "live", "arrival"))


def ranked_ids(salt):
    return sorted(range(1, 31), key=lambda i: hashlib.sha256(f"{salt}:{i}".encode()).hexdigest())


def make_trace(spec, replicate):
    if replicate not in (0, 1):
        raise ValueError("Expected block zero or one")
    template = json.loads((HERE / "calibrated-template.json").read_text())
    burst = next(c for c in template["conditions"] if c["name"] == "burst")
    burst["policy_order"] = list(ORDERS[replicate])
    seed_base = spec["seed_bases"][replicate]
    for item in burst["arrivals"]:
        item["seed"] = seed_base + item["id"]
    return dict(name=spec["name"], replicate=replicate, seed_base=seed_base,
                scale_seconds=template["scale_seconds"], conditions=[burst],
                planned_measured_requests=36)


def validate_trace(spec, trace):
    if trace != make_trace(spec, trace["replicate"]):
        raise ValueError("Trace differs from frozen recipe")


if __name__ == "__main__":
    spec = json.loads((HERE / "spec.json").read_text())
    for block in (0, 1):
        (HERE / f"trace-r{block}.json").write_text(
            json.dumps(make_trace(spec, block), indent=2) + "\n")
