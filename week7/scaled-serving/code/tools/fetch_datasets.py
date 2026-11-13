#!/usr/bin/env python3
"""Fetch and freeze the datasets named in configs/datasets.json.

Uses only the Python standard library. The datasets-server rows API provides
normalized rows; the Hugging Face API provides the pinned revision, license and
source-file list. The parquet source file is downloaded and hashed for
provenance when available.

Run from the repository root:
    python3 week7/scaled-serving/code/tools/fetch_datasets.py
    python3 week7/scaled-serving/code/tools/fetch_datasets.py --force
"""
import argparse
import hashlib
import json
import logging
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs/datasets.json"
RAW = ROOT / "data/raw"
LOGS = ROOT / "logs/p0"
API = "https://huggingface.co/api/datasets/"
ROWS = "https://datasets-server.huggingface.co/rows"
RESOLVE = "https://huggingface.co/datasets/{dataset}/resolve/{revision}/{path}"
USER_AGENT = "larb-scaled-serving-p0/1.0"


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def get_json(url, retries=6, timeout=60):
    last = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = exc
            retry_after = exc.headers.get("Retry-After")
            delay = float(retry_after) if retry_after and retry_after.isdigit() else 10.0 * (attempt + 1)
            time.sleep(min(delay, 60.0))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last = exc
            time.sleep(min(2.0 ** attempt, 30.0))
    raise RuntimeError(f"GET failed: {url}: {last}")


def download(url, target, retries=4, timeout=120):
    last = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = response.read()
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(data)
            temporary.replace(target)
            return digest(target), len(data)
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
            time.sleep(1.5 ** attempt)
    raise RuntimeError(f"download failed: {url}: {last}")


def fetch_rows(dataset_id, page=100, timeout=60):
    rows = []
    features = None
    offset = 0
    while True:
        query = urllib.parse.urlencode(dict(dataset=dataset_id, config="default",
                                            split="train", offset=offset, length=page))
        payload = get_json(f"{ROWS}?{query}", timeout=timeout)
        if features is None:
            features = payload.get("features")
        batch = payload.get("rows", [])
        if not batch:
            break
        rows.extend(item["row"] for item in batch)
        offset += len(batch)
        if len(batch) < page:
            break
    return rows, features


def parquet_path(siblings):
    names = [item.get("rfilename", "") for item in siblings]
    candidates = [name for name in names if name.endswith(".parquet")]
    if not candidates:
        return None
    preferred = [name for name in candidates if "train" in name]
    return (preferred or candidates)[0]


def jsonl_path(siblings):
    names = [item.get("rfilename", "") for item in siblings]
    candidates = [name for name in names if name.endswith(".jsonl")]
    if not candidates:
        return None
    preferred = [name for name in candidates if "test" in name] or candidates
    return preferred[0]


def read_jsonl(path):
    rows = []
    with path.open() as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows, sorted(rows[0]) if rows else []


def fetch_one(entry, force=False):
    dataset_id = entry["id"]
    slug = entry["slug"]
    out = RAW / slug
    out.mkdir(parents=True, exist_ok=True)
    meta_path = out / "meta.json"
    rows_path = out / "rows.json"

    info = get_json(API + urllib.parse.quote(dataset_id, safe="/"))
    revision = info.get("sha")
    if not revision:
        raise RuntimeError(f"missing revision for {dataset_id}")
    if meta_path.exists() and not force:
        existing = json.loads(meta_path.read_text())
        if existing.get("revision") == revision and rows_path.exists():
            logging.info("skip %s at %s", dataset_id, revision)
            return existing

    jsonl_source = jsonl_path(info.get("siblings", []))
    parquet_source = parquet_path(info.get("siblings", []))
    source_path = jsonl_source or parquet_source
    source_hash = None
    source_bytes = None
    source_error = None
    if jsonl_source:
        target = out / "source.jsonl"
        if target.exists() and not force:
            source_hash, source_bytes = digest(target), target.stat().st_size
        else:
            try:
                url = RESOLVE.format(dataset=dataset_id, revision=revision, path=jsonl_source)
                source_hash, source_bytes = download(url, target)
            except RuntimeError as exc:
                source_error = str(exc)
                logging.warning("source download failed for %s: %s", dataset_id, exc)
        rows, features = read_jsonl(target)
    else:
        rows, features = fetch_rows(dataset_id)
        if parquet_source:
            target = out / "source.parquet"
            if target.exists() and not force:
                source_hash, source_bytes = digest(target), target.stat().st_size
            else:
                try:
                    url = RESOLVE.format(dataset=dataset_id, revision=revision, path=parquet_source)
                    source_hash, source_bytes = download(url, target)
                except RuntimeError as exc:
                    source_error = str(exc)
                    logging.warning("source download failed for %s: %s", dataset_id, exc)

    rows_path.write_text(json.dumps({"dataset": dataset_id, "revision": revision,
                                     "features": features, "rows": rows},
                                    ensure_ascii=False, indent=2) + "\n")

    card = info.get("cardData", {}) or {}
    config = json.loads(CONFIG.read_text())
    role = next((role for role, entries in config.items()
                 if isinstance(entries, list) and entry in entries), None)
    meta = {
        "dataset": dataset_id,
        "slug": slug,
        "revision": revision,
        "license": card.get("license"),
        "card_keys": sorted(card),
        "source_file": source_path,
        "source_sha256": source_hash,
        "source_bytes": source_bytes,
        "source_error": source_error,
        "features": features,
        "row_count": len(rows),
        "expected_rows": entry.get("expected_rows"),
        "role": role,
        "exposure": entry.get("exposure"),
        "answer_type": entry.get("answer_type"),
        "rows_sha256": digest(rows_path),
        "fetched_at": utc_now(),
    }
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n")
    if len(rows) != entry.get("expected_rows"):
        logging.warning("%s row count %s != expected %s", dataset_id, len(rows), entry.get("expected_rows"))
    logging.info("fetched %s rows=%d revision=%s", dataset_id, len(rows), revision)
    return meta


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="dataset ids or slugs to fetch")
    parser.add_argument("--sleep", type=float, default=3.0, help="seconds between datasets")
    args = parser.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s",
                        handlers=[logging.FileHandler(LOGS / "fetch_datasets.log"),
                                  logging.StreamHandler(sys.stdout)])
    config = json.loads(CONFIG.read_text())
    entries = []
    for role in ("main", "bridge", "screen", "filler"):
        entries.extend(config.get(role, []))
    if args.only:
        wanted = set(args.only)
        entries = [entry for entry in entries if entry["id"] in wanted or entry["slug"] in wanted]
    results = []
    failures = []
    for entry in entries:
        try:
            results.append(fetch_one(entry, force=args.force))
        except Exception as exc:
            logging.exception("failed %s", entry.get("id"))
            failures.append({"dataset": entry.get("id"), "error": repr(exc)})
        time.sleep(args.sleep)
    summary = {"fetched_at": utc_now(), "datasets": results, "failures": failures}
    (RAW / "manifest.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"datasets": len(results), "failures": len(failures)}, indent=2))
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()

