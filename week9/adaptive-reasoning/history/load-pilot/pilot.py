"""Four-arm one-GPU pilot using the existing LARB server, replay and grader."""

import asyncio
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import aiohttp
from larb_scaled import analysis, client, config, datasets, runner

root = Path(os.environ["PILOT_ROOT"])
out = Path(os.environ.get("PILOT_EVIDENCE_DIR", root / "evidence"))
port = 18765
url = f"http://127.0.0.1:{port}"
arms = ["fixed4k", "fixed8k", "arrival", "live"]
manifest = json.loads((root/"freeze.json").read_text())
questions = manifest["pilot_holdout"]
calibration = manifest["calibration"]
assert len(questions) == 24 and len(calibration) == 12
assert len({q["question_id"] for q in questions+calibration}) == 36


def write_inputs():
    path = config.DATA_DIR/"processed/questions.jsonl"
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open("w") as stream:
        for q in questions+calibration:
            row = dict(q, prompt=datasets.prompt_for(q["problem"]), pool="Omni-MATH",
                       exposure="benchmark", answer_type="integer")
            stream.write(json.dumps(row)+"\n")


def trace(name, cohort, schedule, deadline, seed):
    rows = [dict(question_id=q["question_id"], reference=q["answer"], arrival_s=t,
                 deadline_s=deadline, trace_id=f"{name}-{i}", seed=seed+17*i,
                 scored=True, initial_budget=None, **{"class":"signal"})
            for i,(q,t) in enumerate(zip(cohort,schedule,strict=True))]
    path = out/"traces"/f"{name}.jsonl"
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text("".join(json.dumps(r)+"\n" for r in rows))
    return rows,path


async def phase(session, name, arm, rows, path, deadline, *, warmup=False, diagnostic=False):
    desc = runner.make_phase(f"{name}-{arm}", name, arm, path, deadline_s=deadline,
                             drain_allowance_s=240, injection_lag_limit_seconds=.1)
    state = await client.run_phase(session,url,desc,rows,out)
    raw = analysis.load_requests(out)
    scored = analysis.build_rows(rows,state,raw)
    expected = [analysis.runtime_key(name,arm,row) for row in rows]
    clients = {r["key"]: r for r in state["client_records"]}
    timing = []
    for key in expected:
        r = raw.get(key,{})
        fields = ("scheduled","handler_entry","received","engine_submission")
        if any(r.get(field) is None for field in fields):
            continue
        scheduled,entry,received,submitted = (r[field] for field in fields)
        timing.append(dict(key=key,handler_lag_s=entry-scheduled,setup_s=received-entry,
                           ingress=r.get("ingress", {}), transport=clients.get(key, {}).get("transport", {}),
                           scheduled=scheduled, handler_entry=entry,
                           snapshot_s=r.get("snapshot_seconds"),prompt_s=r.get("prompt_seconds"),
                           stream_dispatch_s=submitted-received,server_lag_s=received-scheduled,
                           engine_submission_lag_s=submitted-scheduled))
    validity = dict(client_max_s=state["max_injection_lag_seconds"],
                    server_max_s=max((r["server_lag_s"] for r in timing),default=None),
                    engine_submission_max_s=max((r["engine_submission_lag_s"] for r in timing),default=None),
                    client_errors=state["errors"],planned=len(rows),recorded_receipts=len(timing),
                    requests=timing)
    complete = (not state["errors"] and len(timing)==len(rows)
                and all(r["complete"] for r in scored)
                and all(min(r["handler_lag_s"],r["setup_s"],r["stream_dispatch_s"])>=0 for r in timing))
    validity["timing_passed"] = (complete and state["injection_valid"]
        and validity["engine_submission_max_s"] <= .25)
    validity["valid"] = complete if warmup else validity["timing_passed"]
    config.write_json(out/"validity"/f"{name}-{arm}.json",validity)
    print(json.dumps({k:v for k,v in validity.items() if k!="requests"}),flush=True)
    if diagnostic:
        return validity
    if not validity["valid"]:
        raise RuntimeError(f"Invalid replay {name}-{arm}; see validity record")
    if warmup:
        return None
    summary = analysis.summarize_phase(scored,state)
    summary["observation_s"] = max(r["arrival_s"] for r in rows)+deadline
    summary["goodput_per_minute"] = 60*summary["correct_on_time"]/summary["observation_s"]
    summary["short_admissions"] = sum(r["initial_budget"]==4096 for r in scored)
    summary["deadline_sweep"] = {
        str(ratio):sum(r["correct"] and r["latency_seconds"]<=deadline*ratio for r in scored)
        for ratio in (.8,.9,1.,1.1,1.2)}
    summary["short_cut_positions"] = [
        event["tokens"] for r in scored for event in raw[r["key"]].get("cut_events",[])]
    config.write_json(out/("timing" if name=="timing-gate" else "scored")/f"{name}-{arm}.json",dict(summary=summary,rows=scored))
    print(json.dumps(summary),flush=True)
    return summary,scored


def transport_trace():
    trace = aiohttp.TraceConfig()
    events = ("connection_queued_start", "connection_queued_end", "connection_create_start",
              "connection_create_end", "connection_reuseconn", "request_headers_sent",
              "request_chunk_sent")
    for event in events:
        async def stamp(_session, context, _params, name=event):
            if context.trace_request_ctx is not None:
                context.trace_request_ctx[name] = time.monotonic()
        getattr(trace, f"on_{event}").append(stamp)
    return trace


async def experiment(server):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=900),
                                     trace_configs=[transport_trace()]) as session:
        async def ready():
            while server.poll() is None:
                try:
                    async with session.get(url+"/health",timeout=2) as response:
                        if response.status==200:
                            return
                except (aiohttp.ClientError,asyncio.TimeoutError):
                    pass
                await asyncio.sleep(2)
            raise RuntimeError("Serving process exited during startup")
        try:
            await asyncio.wait_for(ready(),720)
        except asyncio.TimeoutError as exc:
            raise RuntimeError("Server failed the 12-minute readiness guard; inspect server.log") from exc
        frozen = json.loads((root/"calibration-lock.json").read_text())
        assert frozen["slots"]==4 and frozen["threshold"]==1
        deadline = frozen["deadline_s"]
        wave_interval = frozen["quiet_interval_s"]
        delay = frozen["burst_delay_s"]
        recovery = frozen["recovery_wave_s"]
        rows,p = trace("warmup",calibration[8:],[0.]*4,deadline,881000)
        for row in rows:
            row.update(scored=False,initial_budget=256,**{"class":"filler"})
        p.write_text("".join(json.dumps(row)+"\n" for row in rows))
        await phase(session,"warmup","fixed4k",rows,p,deadline,warmup=True)
        if "--ingress-only" in sys.argv:
            rows,p = trace("ingress-diagnostic",calibration,[0.]*4+[delay]*4+[recovery]*4,deadline,881300)
            await phase(session,"ingress-diagnostic","fixed8k",rows,p,deadline,diagnostic=True)
            return
        # Validate the late quiet wave that the shorter burst gate never reached.
        rows,p = trace("timing-gate",calibration,
                       [0.]*4+[wave_interval]*4+[2*wave_interval]*4,deadline,881300)
        await phase(session,"timing-gate","fixed4k",rows,p,deadline)
        summaries=[]
        for i,(name,cohort,schedule) in enumerate([
            ("quiet",questions[:12],[0.]*4+[wave_interval]*4+[2*wave_interval]*4),
            ("burst-a",questions[:12],[0.]*4+[delay]*4+[recovery]*4),
            ("burst-b",questions[12:],[0.]*4+[delay]*4+[recovery]*4),
        ]):
            rows,p = trace(name,cohort,schedule,deadline,920000+(0 if i<2 else 2000))
            order = [arms[j] for j in ((0,1,2,3),(2,3,1,0),(3,2,0,1))[i]]
            for arm in order:
                report,_ = await phase(session,name,arm,rows,p,deadline)
                summaries.append(report)
                config.write_json(out/"pilot-summary.json",summaries)


if __name__=="__main__":
    write_inputs()
    if "--prepare-only" in sys.argv:
        print("Frozen inputs: 24 pilot and 12 disjoint calibration questions.")
        sys.exit(0)
    out.mkdir(parents=True,exist_ok=True)
    env=runner.server_env({"LARB_ENFORCE_EAGER":"1","LARB_CONTRACT":"legacy",
                           "LARB_PRETOKENIZE_FROZEN":"1"},out,port)
    with (out/"server.log").open("w") as log:
        server=subprocess.Popen([sys.executable,"-u",str(root/"server_start.py")],
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
