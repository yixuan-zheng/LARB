#!/usr/bin/env python3
"""CPU-only P1 readiness check: syntax, sbatch, plans, data and model path."""
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

from larb_scaled import config  # noqa: E402


def main():
    results = {"generated_at": config.utc_now(), "checks": {}}
    failures = []
    for path in sorted((ROOT / "code").rglob("*.py")):
        try:
            py_compile.compile(str(path), doraise=True)
            results["checks"].setdefault("python_syntax", []).append(str(path.relative_to(ROOT)))
        except py_compile.PyCompileError as exc:
            failures.append(f"syntax: {path}: {exc}")
    for script in sorted((ROOT / "code/sbatch").glob("*.sbatch")):
        result = subprocess.run(["bash", "-n", str(script)], capture_output=True, text=True)
        if result.returncode != 0:
            failures.append(f"sbatch: {script}: {result.stderr.strip()}")
    for plan in ("p1", "p2"):
        path = ROOT / "results/p0" / f"dry-run-{plan}" / "plan.json"
        if path.exists():
            phases = json.loads(path.read_text())
            results["checks"][f"dry_run_{plan}"] = {"phases": len(phases),
                                                    "requests": sum(p["request_count"] for p in phases)}
        else:
            failures.append(f"missing dry-run plan: {path}")
    model = os.environ.get("LARB_MODEL_PATH", config.load_protocol()["model"]["local_path_default"])
    results["checks"]["model_path"] = {"path": model, "exists": Path(model).exists()}
    if not Path(model).exists():
        failures.append(f"model path missing: {model}")
    results["checks"]["protocol"] = config.validate_all()[0]["name"]
    results["checks"]["gpu_visible"] = subprocess.run(["bash", "-lc", "command -v nvidia-smi"],
                                                       capture_output=True, text=True).returncode == 0
    results["checks"]["note"] = "GPU entrypoints are syntax-checked only; P1 execution is not authorized here."
    results["failures"] = failures
    results["ok"] = not failures
    config.write_json(ROOT / "results/p0/p1_readiness.json", results)
    print(json.dumps(results, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
