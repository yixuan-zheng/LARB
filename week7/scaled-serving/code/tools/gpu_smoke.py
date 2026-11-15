#!/usr/bin/env python3
"""One-request GPU smoke test for the scaled server and controller.

Starts the local server, sends one 4k-budget request from the mechanics trace,
prints the resolved record, and stops the server. This validates the engine
wiring (cue position, state bus, cap flag) before a gate spends GPU time.
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path

SCALED = Path(__file__).resolve().parents[2]
ROOT = SCALED.parents[1]
sys.path.insert(0, str(SCALED / "code"))

from larb_scaled import client, config  # noqa: E402


async def main():
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else SCALED / "results/p1/smoke"
    out = out if out.is_absolute() else (ROOT / out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    port = 18790
    env = dict(os.environ)
    protocol = config.load_protocol()
    env.update({
        "LARB_OUT": str(out), "LARB_PORT": str(port),
        "LARB_MODEL_PATH": os.environ.get("LARB_MODEL_PATH",
                                          protocol["model"]["local_path_default"]),
        "LARB_MAX_NUM_SEQS": "32", "LARB_ENFORCE_EAGER": "1",
        "LARB_CONTRACT": "legacy",
        "PYTHONPATH": str(SCALED / "code"),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1",
        "TOKENIZERS_PARALLELISM": "false", "VLLM_WORKER_MULTIPROC_METHOD": "spawn",
        "VLLM_USE_FLASHINFER_SAMPLER": "0", "VLLM_ATTENTION_BACKEND": "FLASH_ATTN",
        "VLLM_USE_V1": "1", "VLLM_ENABLE_V1_MULTIPROCESSING": "0",
    })
    log = (out / "server.log").open("w")
    server = subprocess.Popen([sys.executable, "-m", "larb_scaled.server"],
                              cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT,
                              start_new_session=True)
    import aiohttp
    base = f"http://127.0.0.1:{port}"
    trace = SCALED / "artifacts/traces/gate-mechanics.jsonl"
    row = json.loads(trace.read_text().splitlines()[0])
    try:
        timeout = aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=None)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            await client.wait_health(session, base, timeout=900)
            async with session.post(base + "/phase", json=dict(
                    phase="gate-mechanics", arm="fixed4k",
                    condition="gate-mechanics")) as response:
                print("phase:", response.status, await response.text())
            key = client.key_for(dict(condition="gate-mechanics", arm="fixed4k"), row)
            body = dict(key=key, trace_id=row["trace_id"], question_id=row["question_id"],
                        seed=row["seed"], **{"class": row["class"]}, scored=True,
                        initial_budget=None, scheduled=time.monotonic(),
                        deadline_s=1800.0)
            started = time.monotonic()
            async with session.post(base + "/generate", json=body) as response:
                print("generate:", response.status)
                async for line in response.content:
                    if line.strip():
                        print("stream:", line.decode().strip())
            elapsed = time.monotonic() - started
            record = json.loads((out / "requests" / f"{key}.json").read_text())
            summary = {field: record.get(field) for field in
                       ("complete", "error", "initial_budget", "final_budget", "cue_start",
                        "scheduler_start", "waiting_at_arrival", "capped", "preemptions")}
            summary.update(tokens=len(record.get("token_ids") or []),
                           elapsed=round(elapsed, 1), answer_cap=record.get("answer_cap"),
                           close_id=record.get("close_id"), eos_id=record.get("eos_id"))
            cue = record.get("cue_ids") or []
            ids = record.get("token_ids") or []
            start = record.get("cue_start")
            summary["cue_matches"] = bool(start is not None and cue and
                                          ids[start:start + len(cue)] == cue)
            summary["token_tail"] = ids[-3:]
            config.write_json(out / "smoke.json", summary)
            print(json.dumps(summary, indent=2))
    finally:
        import signal
        try:
            os.killpg(server.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            server.wait(timeout=30)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(server.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        log.close()


if __name__ == "__main__":
    asyncio.run(main())
