import json
import statistics
import sys
from pathlib import Path

root = Path(sys.argv[1])
manifest = json.loads((root / "freeze.json").read_text())
paths = (root / "smoke/solves").glob("smoke--*.json")
rows = [json.loads(path.read_text()) for path in paths]
for budget in manifest["budgets"].values():
    group = [row for row in rows if row["budget"] == budget]
    result = {"budget": budget, "correct": sum(row["correct"] for row in group),
              "completed": len(group), "planned": 48}
    if group:
        result.update(
            mean_reasoning=statistics.mean(row["audit"]["thinking_tokens"] for row in group),
            mean_output=statistics.mean(row["output_tokens"] for row in group),
            mean_input=statistics.mean(row["prompt_tokens"] for row in group))
    print(json.dumps(result))
