"""Run the pre-declared AIME 2025+2026 candidate preview on the GPU.

The phase construction, contract, engine settings and preview rule are the
frozen ones (`runner._phase`, `configs/qualify.json`); only the question set and
the trace names differ from the Omni-MATH qualification.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from larb_week8 import config, preview, runner

CANDIDATE = "aime-2025-2026-v1"
TRACE_DIR = config.ARTIFACTS_DIR / "traces-candidates"
CONDITIONS = {24: "gate-aime-preview", 48: "gate-aime-preview48"}
QUESTIONS_PATH = config.DATA_DIR / "candidates" / CANDIDATE / "questions.jsonl"


def main() -> dict:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--size", type=int, choices=[24, 48], default=24)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--trace", type=Path,
                        help="override the trace file (stability replicates)")
    parser.add_argument("--condition", help="override the phase condition name")
    parser.add_argument("--analysis-python", default=sys.executable)
    args = parser.parse_args()
    out = Path(args.out)
    condition = args.condition or CONDITIONS[args.size]
    path = args.trace or (TRACE_DIR / f"{condition}.jsonl")
    if not path.exists():
        raise SystemExit(f"missing trace {path}; run tools/build_candidate_pool.py first")
    out.mkdir(parents=True, exist_ok=True)
    if (out / "phases.json").exists():
        raise SystemExit(f"{out} already has a run; use a fresh directory")
    phases = [runner._phase(f"preview-{arm}", condition, arm, path, 1800.0, 600.0)
              for arm in ("fixed4k", "fixed6k", "fixed8k")]
    runner.run_sequence(phases, out)

    analysis = (
        "import json; from pathlib import Path;"
        "from larb_week8 import config, preview;"
        f"config.QUESTIONS_PATH = Path({str(QUESTIONS_PATH)!r});"
        f"result = preview.main(Path({str(out)!r}), Path({str(out)!r}), {args.size});"
        "print(json.dumps(result['decision'], indent=1))")
    env = dict(runner._analysis_env())
    env["PYTHONPATH"] = str(config.WEEK8_CODE) + ":" + str(config.WEEK7_CODE)
    completed = subprocess.run([args.analysis_python, "-c", analysis], env=env,
                               cwd=str(config.REPO_ROOT), text=True)
    if completed.returncode != 0:
        raise SystemExit("preview analysis failed")
    return json.loads((out / f"preview-{args.size}.json").read_text())


if __name__ == "__main__":
    main()
