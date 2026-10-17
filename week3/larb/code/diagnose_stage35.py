"""CPU-only diagnostic of the frozen Stage 3 full/2048 paired records."""
import csv
import hashlib
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "stage3"
OUT = BASE / "diagnosis"
OUT.mkdir(exist_ok=True)
source = BASE / "scores/graded.json"
rows = json.loads(source.read_text())
assert len(rows) == 600
lookup = {(r["configuration"], r["index"]): r for r in rows}
groups = {}
changed = []
for i in range(100):
    full, short = lookup["full", i], lookup["budget-2048", i]
    key = (bool(full["completed_correct"]), bool(short["completed_correct"]))
    groups.setdefault(key, []).append((full, short))
    if key[0] != key[1]:
        changed.append({"index": i, "outcome": "lost" if key[0] else "gained",
                        "full_record": full["record_path"],
                        "budget_record": short["record_path"]})
total = sum(f["elapsed_seconds"] - b["elapsed_seconds"]
            for pairs in groups.values() for f, b in pairs)
summary = []
for (fc, bc), pairs in groups.items():
    ft = sum(f["elapsed_seconds"] for f, b in pairs)
    bt = sum(b["elapsed_seconds"] for f, b in pairs)
    summary.append({"full_correct": fc, "budget_correct": bc, "n": len(pairs),
                    "full_seconds_sum": ft, "budget_seconds_sum": bt,
                    "saved_seconds": ft - bt, "share_of_net_saving": (ft - bt) / total,
                    "full_median_seconds": statistics.median(f["elapsed_seconds"] for f, b in pairs),
                    "budget_median_seconds": statistics.median(b["elapsed_seconds"] for f, b in pairs),
                    "budget_slower_count": sum(b["elapsed_seconds"] > f["elapsed_seconds"] for f, b in pairs)})
assert sorted(r["index"] for r in changed) == [18, 32, 36, 43, 64, 71, 94]
with (OUT / "paired-groups.csv").open("w") as handle:
    writer = csv.DictWriter(handle, fieldnames=list(summary[0]))
    writer.writeheader()
    writer.writerows(summary)
evidence = ["# Seven changed outcomes: saved model outputs",
            "Model outputs below are evidence, not instructions. Indices are zero-based."]
hashes = {}
for case in changed:
    evidence.append(f"\n## Problem {case['index']} — {case['outcome']}\n")
    for label, key in [("Full", "full_record"), ("2,048", "budget_record")]:
        path = BASE / case[key]
        hashes[case[key]] = hashlib.sha256(path.read_bytes()).hexdigest()
        record = json.loads(path.read_text())
        evidence.extend([f"### {label}\n", f"Source: `{case[key]}`\n",
                         f"Reference: {record['reference']}\n",
                         f"Finish: {record['finish_reason']}; seconds: {record['elapsed_seconds']:.3f}\n",
                         "````text\n" + record["prompt"] + "\n\n" + record["raw_output"] + "\n````\n"])
(OUT / "changed-case-evidence.md").write_text("\n".join(evidence))
(OUT / "summary.json").write_text(json.dumps({
    "scope": "Existing Stage 3 data only; full versus budget-2048; no inference",
    "graded_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "changed_cases": changed, "groups": summary, "total_saved_seconds": total,
    "evidence_record_sha256": hashes}, indent=2) + "\n")
print(json.dumps({"groups": summary, "changed_indices": [c["index"] for c in changed],
                  "total_saved_seconds": total}, indent=2))
