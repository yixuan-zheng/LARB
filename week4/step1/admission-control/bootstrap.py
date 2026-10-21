"""Resolve immutable Week 3 imports from this checkout, never from CWD."""
from pathlib import Path
import os
import sys

REPO = Path(__file__).resolve().parents[3]
LEGACY = Path(os.environ.get('LARB_WEEK3_ROOT', REPO / 'week3/larb')).resolve()
sys.path.extend([str(LEGACY / 'burst-policy'), str(LEGACY / 'serving-proof')])
