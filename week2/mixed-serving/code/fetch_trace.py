"""Download the Azure LLM inference trace CSVs once, into ``traces/raw/``.

Run this on a machine with network access; every run afterwards is offline.  The
raw files are git-ignored because they are redistributable but large relative to
the committed normalized windows; their sha256 goes into every derived artifact,
so a window can always be traced back to the exact bytes it came from.

    python code/fetch_trace.py                 # both files -> traces/raw/
    python code/fetch_trace.py --verify-only   # check hashes/sizes, download nothing

Licence: the Azure public dataset is CC-BY-4.0; citation (Splitwise, ISCA 2024)
is recorded in ``traces/README.md`` next to the files.
"""
from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "traces" / "raw"
URLS = {
    "AzureLLMInferenceTrace_conv.csv":
        "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/"
        "AzureLLMInferenceTrace_conv.csv",
    "AzureLLMInferenceTrace_code.csv":
        "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/"
        "AzureLLMInferenceTrace_code.csv",
}
#: Sizes of the copies this harness was built against (a sanity check, not a gate).
EXPECTED_BYTES = {"AzureLLMInferenceTrace_conv.csv": 719188,
                  "AzureLLMInferenceTrace_code.csv": 320117}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch(name: str, url: str, overwrite: bool = False) -> dict:
    RAW.mkdir(parents=True, exist_ok=True)
    dest = RAW / name
    if dest.exists() and not overwrite:
        return {"name": name, "status": "present", "bytes": dest.stat().st_size,
                "sha256": sha256(dest), "url": url}
    with urllib.request.urlopen(url, timeout=120) as response:  # noqa: S310
        payload = response.read()
    dest.write_bytes(payload)
    return {"name": name, "status": "downloaded", "bytes": len(payload),
            "sha256": hashlib.sha256(payload).hexdigest(), "url": url}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    ok = True
    for name, url in URLS.items():
        dest = RAW / name
        if args.verify_only:
            if not dest.exists():
                print(f"[fetch] MISSING {name}")
                ok = False
                continue
            size, digest = dest.stat().st_size, sha256(dest)
            flag = "ok" if EXPECTED_BYTES.get(name) in (None, size) else "SIZE CHANGED"
            print(f"[fetch] {name} {size} bytes sha256={digest} {flag}")
            continue
        info = fetch(name, url, args.overwrite)
        print(f"[fetch] {info['status']:<11} {name} {info['bytes']} bytes "
              f"sha256={info['sha256']}")
    if args.verify_only and not ok:
        sys.exit(1)
    print("[fetch] next: python code/workload.py azure-windows --out traces")


if __name__ == "__main__":
    main()
