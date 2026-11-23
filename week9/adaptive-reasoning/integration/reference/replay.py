"""One mixed-workload burst, identical across six policies."""
import asyncio
import os
import signal
import subprocess
import sys

import aiohttp

import pilot
from routed_contract import ARMS


async def ready(server, session):
    while server.poll() is None:
        try:
            async with session.get(pilot.url+"/health", timeout=2) as response:
                if response.status == 200:
                    return
        except (aiohttp.ClientError, asyncio.TimeoutError):
            pass
        await asyncio.sleep(2)
    raise RuntimeError("Server exited before readiness")


async def preconnect(session):
    async def one():
        async with session.get(pilot.url+"/health") as response:
            response.raise_for_status()
            await response.read()
    await asyncio.gather(*(one() for _ in range(8)))


def rotated_arms():
    return ("coin-151", "coin-load-151", "coin-load-411", "coin-411")


async def experiment(server):
    connector = aiohttp.TCPConnector(keepalive_timeout=180)
    async with aiohttp.ClientSession(connector=connector,timeout=aiohttp.ClientTimeout(total=2100),
                                    trace_configs=[pilot.transport_trace()]) as session:
        await asyncio.wait_for(ready(server,session),720)
        deadline = 220
        rows,path = pilot.trace("warmup",pilot.calibration[:4],[0.]*4,deadline,881000)
        for row in rows:
            row.update(scored=False,initial_budget=256,**{"class":"filler"})
        path.write_text("".join(pilot.json.dumps(row)+"\n" for row in rows))
        await pilot.phase(session,"warmup","fixed4k",rows,path,deadline,warmup=True)
        arrivals = [0.]*6 + [20.]*6
        rows,path = pilot.trace("timing-gate",pilot.calibration,arrivals,deadline,881300)
        await preconnect(session)
        gate = await pilot.phase(session,"timing-gate","combined",rows,path,deadline,diagnostic=True)
        if not gate["valid"]:
            raise RuntimeError("Unscored burst timing gate failed")
        rows,path = pilot.trace("mixed-burst",pilot.questions,[0.]*12+[20.]*12,deadline,920000)
        summaries = []
        rejected = []
        for arm in rotated_arms():
            await preconnect(session)
            try:
                summary,scored = await pilot.phase(session,"mixed-burst",arm,rows,path,deadline)
            except RuntimeError as exc:
                if not str(exc).startswith("Invalid replay "):
                    raise
                rejected.append(arm)
                pilot.config.write_json(pilot.out/"rejected.json",rejected)
                continue
            summary["p95_latency_s"] = pilot.analysis._q([r["latency_seconds"] for r in scored],.95)
            summary["total_prompt_tokens"] = sum(len(raw["prompt_token_ids"]) for key,raw in
                pilot.analysis.load_requests(pilot.out).items() if key.startswith(f"mixed-burst--{arm}--"))
            summaries.append(summary)
            pilot.config.write_json(pilot.out/"pilot-summary.json",summaries)
        if not summaries or rejected:
            raise RuntimeError(f"Incomplete matched replay; rejected arms: {rejected}")


def main():
    pilot.write_inputs()
    pilot.out.mkdir(parents=True,exist_ok=True)
    env = pilot.runner.server_env({"LARB_ENFORCE_EAGER":"1","LARB_CONTRACT":"legacy"},pilot.out,pilot.port)
    with (pilot.out/"server.log").open("w") as log:
        server = subprocess.Popen([sys.executable,"-u",str(pilot.root/"server_start.py")],
            stdout=log,stderr=subprocess.STDOUT,env=env,start_new_session=True)
        try:
            asyncio.run(experiment(server))
        finally:
            if server.poll() is None:
                os.killpg(server.pid,signal.SIGTERM)
                try:
                    server.wait(timeout=20)
                except subprocess.TimeoutExpired:
                    os.killpg(server.pid,signal.SIGKILL)
                    server.wait()


if __name__ == "__main__":
    main()
