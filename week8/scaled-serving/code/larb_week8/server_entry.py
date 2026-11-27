"""GPU entrypoint: frozen week 7 vLLM server with the Week 8 question set.

The week 7 server loads ``data/processed/questions.jsonl`` relative to its own
package.  We do not modify that frozen package; instead we replace its
``load_questions`` function before ``main()`` runs.  The server still uses the
week 7 protocol, contract, policy, controller and telemetry.
"""
from __future__ import annotations

import os

from larb_week8.questions import load_merged_questions
from larb_scaled import controller, server


def _load_week8_questions() -> None:
    questions = load_merged_questions()
    server.QUESTIONS.clear()
    server.QUESTIONS.update(questions)
    print(f"larb_week8 server questions: {len(questions)}", flush=True)


server.load_questions = _load_week8_questions


def main() -> None:
    if not os.environ.get("LARB_OUT"):
        raise SystemExit("LARB_OUT must point at the run directory")
    # P3C extension: allow a pre-declared cut target (4k or 6k).  The frozen
    # week 7 controller reads this module global at each control event.
    cut_target = os.environ.get("LARB_CUT_TARGET")
    if cut_target:
        controller.CUT_TARGET = int(cut_target)
        print(f"larb_week8 cut target: {controller.CUT_TARGET}", flush=True)
    server.main()


if __name__ == "__main__":
    main()
