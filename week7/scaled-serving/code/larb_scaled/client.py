"""Asyncio replay client for one or more drained phases.

The client is arm-agnostic: it reads a trace, adds the arm to the runtime key,
submits every request at its scheduled offset, and writes a separate client
record. It never kills a request for missing its scientific deadline.
"""
import argparse
import asyncio
import json
import os
import time
from pathlib import Path

from larb_scaled import config


def load_trace(path):
    rows = []
    with Path(path).open() as handle:
        for line in handle:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def key_for(phase, row):
    return f"{phase['condition']}--{phase['arm']}--{row['class']}--{row['question_id']}--{row['seed']}"


async def wait_health(session, base, timeout=900):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            async with session.get(base + "/health") as response:
                if response.status == 200:
                    return
        except Exception:
            pass
        await asyncio.sleep(2)
    raise RuntimeError("server health timeout")


async def wait_drain(session, base, timeout=3600):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        async with session.get(base + "/health") as response:
            body = await response.json()
            if not body.get("active"):
                return
        await asyncio.sleep(2)
    raise RuntimeError("server drain timeout")


async def run_phase(session, base, phase, trace_rows, out):
    async with session.post(base + "/phase", json=dict(
            phase=phase["name"], arm=phase["arm"], condition=phase["condition"])) as response:
        response.raise_for_status()
    await asyncio.sleep(0.5)
    epoch = time.monotonic() + 0.5
    records = []

    async def one(row):
        scheduled = epoch + row["arrival_s"]
        await asyncio.sleep(max(0.0, scheduled - time.monotonic()))
        submitted = time.monotonic()
        key = key_for(phase, row)
        body = dict(key=key, trace_id=row["trace_id"], question_id=row["question_id"],
                    seed=row["seed"], **{"class": row["class"]}, scored=row["scored"],
                    initial_budget=row["initial_budget"], scheduled=scheduled,
                    deadline_s=row["deadline_s"])
        data = None
        error = None
        try:
            async with session.post(base + "/generate", json=body) as response:
                response.raise_for_status()
                async for line in response.content:
                    if line.strip():
                        data = json.loads(line)
            if not data or not data.get("finished"):
                error = "incomplete_stream"
        except Exception as exc:  # a failed request is a failure, not a phase abort
            error = repr(exc)
        record = dict(key=key, trace_id=row["trace_id"], condition=phase["condition"],
                      arm=phase["arm"], question_id=row["question_id"], seed=row["seed"],
                      **{"class": row["class"]}, scored=row["scored"], scheduled=scheduled,
                      client_submitted=submitted,
                      server_finished=(data or {}).get("monotonic"),
                      latency_seconds=((data or {}).get("monotonic") - scheduled
                                        if (data or {}).get("monotonic") is not None else None),
                      injection_lag_seconds=submitted - scheduled,
                      outcome=("ok" if error is None else "error"), error=error,
                      deadline=scheduled + row["deadline_s"],
                      timely=(error is None and
                              (data or {}).get("monotonic") is not None and
                              (data["monotonic"] - scheduled) <= row["deadline_s"]))
        config.write_json(Path(out) / "clients" / f"{key}.json", record)
        records.append(record)

    try:
        await asyncio.wait_for(asyncio.gather(*(one(row) for row in trace_rows)),
                               timeout=max(row["arrival_s"] for row in trace_rows) +
                               phase["horizon_s"] + 60)
    finally:
        await wait_drain(session, base, timeout=phase["horizon_s"] + 600)
    phase_record = dict(phase, epoch=epoch, request_count=len(records),
                        errors=sum(1 for r in records if r["outcome"] != "ok"),
                        injection_valid=all(r["injection_lag_seconds"] <=
                                            phase.get("injection_lag_limit_seconds", 1.0)
                                            for r in records),
                        max_injection_lag_seconds=max((r["injection_lag_seconds"] for r in records),
                                                      default=0.0),
                        client_records=records)
    config.write_json(Path(out) / "phases" / f"{phase['name']}.json", phase_record)
    return phase_record


async def run_phases(base, phases, out):
    import aiohttp
    out = Path(out)
    (out / "clients").mkdir(parents=True, exist_ok=True)
    (out / "phases").mkdir(parents=True, exist_ok=True)
    phase_file = out / "phases.json"
    existing = []
    if phase_file.exists():
        try:
            existing = json.loads(phase_file.read_text())
        except json.JSONDecodeError:
            existing = []
    config.write_json(phase_file, existing)
    records = []
    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
    async with aiohttp.ClientSession(timeout=timeout,
                                     connector=aiohttp.TCPConnector(limit=128)) as session:
        await wait_health(session, base)
        for phase in phases:
            rows = load_trace(phase["trace_file"])
            record = await run_phase(session, base, phase, rows, out)
            records.append(record)
            config.write_json(phase_file, existing + records)
    return records


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:18761")
    parser.add_argument("--phases", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args()
    phases = json.loads(args.phases.read_text())
    asyncio.run(run_phases(args.base, phases, args.out))


if __name__ == "__main__":
    main()
