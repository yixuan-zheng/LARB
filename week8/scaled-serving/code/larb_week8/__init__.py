"""Week 8 qualification layer for the frozen week 7 scaled-serving rig.

The week 7 package (``week7/scaled-serving/code/larb_scaled``) is treated as
read-only: its source-lock hash is part of the P1 evidence.  This package
imports that frozen code and adds only the new pool, preview, calibration and
decision machinery.  Importing ``larb_week8`` puts the frozen week 7 code on
``sys.path`` so every submodule can use it without copying it.
"""
import sys
from pathlib import Path

WEEK8_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = WEEK8_ROOT.parents[1]
WEEK7_ROOT = REPO_ROOT / "week7/scaled-serving"
WEEK7_CODE = WEEK7_ROOT / "code"
WEEK7_TOOLS = WEEK7_CODE / "tools"
WEEK8_CODE = WEEK8_ROOT / "code"

for _path in (WEEK7_TOOLS, WEEK7_CODE, WEEK8_CODE):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

__all__ = ["WEEK8_ROOT", "REPO_ROOT", "WEEK7_ROOT", "WEEK7_CODE", "WEEK7_TOOLS", "WEEK8_CODE"]
