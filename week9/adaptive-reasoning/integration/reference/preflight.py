"""CPU checks for spawn safety and the pilot's HTTP replay and scoring path."""

import asyncio
import json
import runpy
import sys
import tempfile
import time
from pathlib import Path

import aiohttp
from aiohttp import web

import pilot


def check_entry_point():
    # spawn re-executes the launching file as __mp_main__. The wrapper must
    # neither import the GPU server nor call its entry point in that process.
    assert "larb_scaled.server" not in sys.modules
    runpy.run_path(str(Path(__file__).with_name("server_start.py")), run_name="__mp_main__")
    assert "larb_scaled.server" not in sys.modules


async def check_replay():
    phase_state = {}
    with tempfile.TemporaryDirectory(prefix="larb-pilot-preflight-") as scratch:
        pilot.out = Path(scratch)
        rows, path = pilot.trace("mock",pilot.questions[:2],[0,.04],15,9400)
        write_json = pilot.config.write_json
        def slow_client_write(path,value):
            if Path(path).parent.name == "clients":
                time.sleep(.16)
            return write_json(path,value)
        pilot.config.write_json = slow_client_write
        expected = {r["question_id"]:r["reference"] for r in rows}

        async def set_phase(request):
            phase_state.update(await request.json())
            return web.json_response({"ok": True})

        async def health(_request):
            return web.json_response({"active":[]})

        async def generate(request):
            body=await request.json()
            arm=phase_state["arm"]
            key=body["key"]
            assert key.startswith(f"mock--{arm}--")
            finish=time.monotonic()
            cut=arm=="live" and body["question_id"]==rows[0]["question_id"]
            budget=4096 if cut or arm=="fixed4k" else 8192
            raw=dict(key=key,complete=True,finished=finish,scheduler_start=finish,
                     received=finish,handler_entry=finish,engine_submission=finish,scheduled=body["scheduled"],
                     token_ids=[11,12,13],close_id=12,eos_id=13,cue_ids=[12],
                     cue_start=1,raw_output=r"\boxed{"+expected[body["question_id"]]+"}",
                     cut_events=[],
                     initial_budget=8192 if cut else budget,final_budget=budget)
            if cut:
                with (pilot.out/"worker.jsonl").open("a") as worker:
                    worker.write(json.dumps({"event":"live_reduction","key":key,
                                             "tokens":1024,"budget":4096})+"\n")
            pilot.config.write_json(pilot.out/"requests"/f"{key}.json",raw)
            return web.Response(text=json.dumps({"finished":True,"monotonic":finish})+"\n")

        app=web.Application()
        app.add_routes([web.post("/phase",set_phase),web.post("/generate",generate),web.get("/health",health)])
        runner=web.AppRunner(app)
        await runner.setup()
        try:
            site=web.TCPSite(runner,"127.0.0.1",0)
            await site.start()
            port=runner.addresses[0][1]
            pilot.url=f"http://127.0.0.1:{port}"
            async with aiohttp.ClientSession(trace_configs=[pilot.transport_trace()]) as session:
                for arm in pilot.arms:
                    summary,scored=await pilot.phase(session,"mock",arm,rows,path,15)
                    assert summary["correct_on_time"]==summary["correct"]==2
                    assert summary["cuts"]==summary["record_omissions"]==int(arm=="live")
                    assert len(scored)==2 and all(summary["deadline_sweep"].values())
                    validity = json.loads((pilot.out / "validity" / f"mock-{arm}.json").read_text())
                    for row in validity["requests"]:
                        trace = row["transport"]
                        assert row["scheduled"] <= trace["request_headers_sent"] <= trace["request_chunk_sent"]
                        assert {"connection_create_end", "connection_reuseconn"} & trace.keys()
        finally:
            pilot.config.write_json = write_json
            await runner.cleanup()


if __name__=="__main__":
    check_entry_point()
    asyncio.run(check_replay())
    print("CPU preflight passed: spawn-safe import, four-arm HTTP replay, scoring and cut accounting.")
