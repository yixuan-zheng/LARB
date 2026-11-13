#!/bin/bash
set -euo pipefail
run_root=${1:?}
answers=${2:?}
python3 - "$run_root/run/status.json" <<'PY'
import json
import sys
with open(sys.argv[1]) as source:
    status = json.load(source)
if not status["complete"] or status["completed"] != status["planned"] or status["planned"] != 928:
    raise SystemExit("Coverage incomplete; grading deferred")
PY
python3 -B "$run_root/release/score.py" "$run_root/run" "$answers" "$run_root/full-summary.json"
