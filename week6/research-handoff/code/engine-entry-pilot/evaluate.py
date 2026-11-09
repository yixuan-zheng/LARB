"""Apply the frozen Week 6 H1 decision to completed block evidence."""
import argparse
import json
from pathlib import Path

from gate import audit_entry

POLICIES = ("arrival", "entry", "live")


def decide(blocks, qualifying_entries):
    if not qualifying_entries:
        return "inconclusive", ["No qualifying measured engine-entry reconsideration"]
    checks = []
    for index, block in enumerate(blocks):
        arrival, entry, live = (block[p] for p in POLICIES)
        live_saving = arrival["total_output_tokens"] - live["total_output_tokens"]
        if live_saving <= 0:
            return "inconclusive", [f"Block {index} has no positive live token saving"]
        entry_saving = arrival["total_output_tokens"] - entry["total_output_tokens"]
        if 2 * entry_saving < live_saving:
            checks.append(f"Block {index} retains less than half the live token saving")
        if entry["correct_on_time"] < live["correct_on_time"]:
            checks.append(f"Block {index} has fewer correct on-time answers than live")
    if sum(b["entry"]["correct"] for b in blocks) < sum(b["arrival"]["correct"] for b in blocks):
        checks.append("Pooled overall correctness falls below HTTP arrival-only")
    return ("reject", checks) if checks else ("support", [])


def read(path):
    return json.loads(path.read_text())


def evaluate(root):
    blocks = []
    qualifying = []
    reasons = []
    for index in range(2):
        folder = root / f"block{index}"
        try:
            assert read(folder / "queue-gate.json")["passed"], "Engineering gate failed"
            assert read(folder / "complete.json")["completed_requests"] == 43, "Incomplete block"
            summary = read(folder / "summary.json")
            phases = {p["policy"]: p for p in summary["summary"] if p["role"] == "measured"}
            assert set(phases) == set(POLICIES), "Policy coverage"
            assert all(p["planned"] == p["present"] == 12 and p["injection_valid"]
                       and p["fully_drained"] for p in phases.values()), "Phase coverage or injection"
            rows = summary["rows"]
            assert len(rows) == 43 and all(r["complete"] and r["reason"] in
                                          ("normal", "answer_cap") for r in rows), "Request coverage"
            entries = audit_entry(folder, "burst-entry--")
            assert set(entries) == {r["key"] for r in rows if r["phase"] == "burst-entry"}
            qualifying.extend(dict(block=index, key=key) for key, event in entries.items()
                              if event["provisional"] == 8192 and event["budget"] == 4096)
            blocks.append(dict(block=index, metrics=phases))
        except (OSError, ValueError, KeyError, AssertionError) as exc:
            reasons.append(f"Block {index}: {type(exc).__name__}: {exc}")
    if reasons:
        status = "inconclusive"
    else:
        status, reasons = decide([b["metrics"] for b in blocks], qualifying)
    result = dict(decision=status, reasons=reasons, qualifying_entries=qualifying,
                  planned_measured=72, planned_probes=14, valid_blocks=blocks)
    (root / "h1-decision.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    evaluate(parser.parse_args().root)
