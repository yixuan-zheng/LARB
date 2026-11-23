"""Verify the forced-cap fixture from controller evidence and API responses."""

import json
import statistics
import sys
from pathlib import Path

out = Path(sys.argv[1])

def load(name):
    path = out / f"{name}.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

agent = {row["key"]: row for row in load("agent")}
key = "tau--2048-stress-0"
state_path = out / "agent-state/request-state" / f"{key}.json"
state = json.loads(state_path.read_text()) if state_path.exists() else {}
follow = agent.get("tau--2048-stress-1", {})
message = follow.get("response", {})
cap = {
    "forced_close": state.get("cue_start"),
    "parsed_call": agent.get(key, {}).get("valid_call", False),
    "tool_result_handled": "delivered" in (message.get("content") or "").lower()
                           and not message.get("tool_calls")
                           and follow.get("finish") == "stop",
}
customers = {}
for model in ("customer-3b", "customer-7b"):
    rows = load(model)
    answered = [row for row in rows if "response" in row]
    customers[model] = {
        "answered": len(answered),
        "planned": 12,
        "median_seconds": statistics.median(row["seconds"] for row in answered) if answered else None,
    }
summary = {"agent_2048_stress": cap, "customer": customers}
(out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
if cap["forced_close"] != 2048 or not cap["parsed_call"] or not cap["tool_result_handled"]:
    sys.exit("2,048-token forced tool-call round trip did not pass")
if any(row["answered"] != row["planned"] for row in customers.values()):
    sys.exit("One or more customer fixtures did not return")
