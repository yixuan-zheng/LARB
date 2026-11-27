#!/usr/bin/env python3
"""Run the P1 slope-record audit with the analysis Python (math_verify)."""
import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401
from larb_week8 import audit  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    audit.main(args.out, args.report)


if __name__ == "__main__":
    main()
