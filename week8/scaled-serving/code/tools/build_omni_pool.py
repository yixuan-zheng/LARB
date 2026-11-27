#!/usr/bin/env python3
"""Build and freeze the Week 8 Omni-MATH fallback pool on CPU.

Run with the serving Python (it has ``tokenizers``):
    PYTHONPATH=week8/scaled-serving/code:week7/scaled-serving/code \
      python week8/scaled-serving/code/tools/build_omni_pool.py
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "code"))

import larb_week8  # noqa: E402,F401  (sets the week 7 import path)
from larb_week8 import pool  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="refetch the frozen source")
    args = parser.parse_args()
    manifest = pool.build_pool(force=args.force)
    print(json.dumps({key: manifest[key] for key in
                      ("pool", "source_rows", "excluded", "candidate_counts",
                       "cohort_counts", "difficulty", "answer_types")}, indent=2))


if __name__ == "__main__":
    main()
