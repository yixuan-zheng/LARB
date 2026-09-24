"""Validate Google's published fixed-depth Gemma 3n FFN presets."""
import csv
import hashlib
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
CSV = ROOT / "public" / "configs.csv"
NAMES = {
    "small": "Config for E2.98B (block-level)",
    "medium": "Config for E3.49B (block-level)",
    "large": "Main model",
}
ROWS = {row["name"]: row for row in csv.DictReader(CSV.open())}
presets = {}
for label, name in NAMES.items():
    row = ROWS[name]
    expressions = re.findall(r"\d[\d_]*\s*\*\s*\d[\d_]*", row["FFN Hidden Dims"])
    widths = [int(a.replace("_", "")) * int(b.replace("_", ""))
              for expression in expressions for a, b in [re.split(r"\s*\*\s*", expression)]]
    assert len(widths) == 35, (label, len(widths))
    assert row["# Layers"] == "35", label
    assert not row["Layers Skipped"].strip(), label
    assert set(widths) <= {8192, 16384}, label
    presets[label] = {
        "name": name,
        "ffn_hidden_dims": widths,
        "num_layers": 35,
        "layers_skipped": [],
        "effective_parameters_billion": float(row["# Effective Params (B)"]),
        "published_mmlu_pt_percent": float(row["MMLU PT accuracy"].strip("%")),
    }
for small, medium, large in zip(*(presets[x]["ffn_hidden_dims"]
                                  for x in ("small", "medium", "large"))):
    assert small <= medium <= large
record = {
    "source": "google/gemma3n-slicing-configs/configs.csv",
    "source_revision": "cf93a642430e7e6891ca38537b5c8d8dd9ba5a7e",
    "csv_sha256": hashlib.sha256(CSV.read_bytes()).hexdigest(),
    "base_model": "google/gemma-3n-E4B",
    "base_revision_checked": "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee",
    "presets": presets,
}
(OUTPUT_DIR / "presets.json").write_text(json.dumps(record, indent=2) + "\n")
for label, data in presets.items():
    print(label, "layers", data["num_layers"], "narrow FFNs",
          data["ffn_hidden_dims"].count(8192), "wide FFNs",
          data["ffn_hidden_dims"].count(16384), "published MMLU PT",
          data["published_mmlu_pt_percent"])
print("PASS: 35 layers, no skips, nested FFN dimensions")
