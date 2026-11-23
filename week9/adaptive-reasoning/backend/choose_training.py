"""Select one measured PACE configuration and submit the protected run."""
import json
import math
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

root = Path.cwd()
cutoff = int(datetime(2026,11,27,0,tzinfo=ZoneInfo("America/New_York")).timestamp())
configurations = {"a100":("A100-80GB","coc-gpu,ice-gpu"),
                  "l40s":("L40S","coc-gpu,ice-gpu")}
jobs = dict(line.split() for line in (root/"gate-jobs").read_text().splitlines())
candidates = []
diagnostics = []
unfinished = []


def run(*command, env=None):
    return subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                          check=False,env=env)


for gpu,job in jobs.items():
    state=run("sacct","-n","-X","-j",job,"-o","State","-P").stdout.strip()
    if not state or state in {"PENDING", "RUNNING", "CONFIGURING", "COMPLETING", "REQUEUED"}:
        unfinished.append(job)
    path=root/f"job-{job}"/"backend-summary.json"
    if state != "COMPLETED" or not path.is_file():
        diagnostics.append({"gpu":gpu,"gate_state":state,"summary":path.is_file()})
        continue
    gate=json.loads(path.read_text())
    rate=gate["output_tokens_per_second"]
    trainer=gate["training_tokens"]/gate["training_seconds"]
    for scope,training,testing in (("full",4096,1296),("reduced",576,360)):
        # Allow longer and partially filled batches than the eight-request gate.
        train_min=math.ceil(1.25*training*(1850/rate+2000/trainer)/60)+38
        eval_min=max(100 if scope=="full" else 45,
                     math.ceil(1.3*testing*1850/rate/60)+20)
        wall=train_min+eval_min+10
        if wall>960:
            diagnostics.append(dict(gpu=gpu,scope=scope,reason="partition wall limit",minutes=wall))
            continue
        feature,parts=configurations[gpu]
        flags=[f"--partition={parts}",f"--gres=gpu:{gpu}:1",f"--constraint={feature}",
               f"--time={wall}","--account=coc","--job-name=larb-mixed-grpo",
               f"--deadline=2026-11-27T00:00:00",f"--output={root}/train-%j.out"]
        environment={**os.environ,"BACKEND_ROOT":str(root),"LARB_SCOPE":scope,
                     "LARB_WALL_MIN":str(wall),"LARB_TRAIN_MIN":str(train_min),
                     "LARB_EVAL_MIN":str(eval_min),"LARB_CUTOFF_EPOCH":str(cutoff),
                     "TZ":"America/New_York"}
        for key in tuple(environment):
            if key.startswith("SLURM_"):
                del environment[key]
        estimate=run("sbatch","--test-only",*flags,str(root/"train.sbatch"),env=environment).stdout
        match=re.search(r"to start at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})",estimate)
        if not match:
            diagnostics.append(dict(gpu=gpu,scope=scope,reason="no start estimate",estimate=estimate.strip()))
            continue
        start=max(time.time(),datetime.fromisoformat(match[1]).replace(tzinfo=ZoneInfo("America/New_York")).timestamp())
        end=start+wall*60
        detail=dict(gpu=gpu,scope=scope,gate=job,start_estimate=match[1],estimated_end_epoch=end,
                    training_minutes=train_min,evaluation_minutes=eval_min,wall_minutes=wall,
                    tokens_per_second=rate)
        if end>cutoff:
            diagnostics.append({**detail,"reason":"completion after extension cutoff"})
            continue
        candidates.append((scope!="full",end,detail,flags,environment))
for _,_,detail,flags,environment in sorted(candidates,key=lambda row:row[:2]):
    if detail["scope"] == "reduced" and unfinished and os.environ.get("LARB_FALLBACK_NOW") != "1":
        diagnostics.append({**detail,"reason":"defer reduced scope while another full candidate is possible"})
        continue
    launched=run("sbatch","--parsable",*flags,str(root/"train.sbatch"),env=environment)
    if launched.returncode==0 and re.fullmatch(r"\d+(;[^\s]+)?",launched.stdout.strip()):
        detail["job"]=launched.stdout.strip()
        (root/"selected-training.json").write_text(json.dumps(detail,indent=2)+"\n")
        print(json.dumps(detail),flush=True)
        for redundant in unfinished:
            cancellation = run("scancel", redundant)
            diagnostics.append(dict(job=redundant,reason="redundant backend gate",
                                    cancellation_status=cancellation.returncode,
                                    detail=cancellation.stdout.strip()))
        break
    diagnostics.append({**detail,"submission":launched.stdout.strip()})
(root/f"selection-diagnostics-{os.environ.get('SLURM_JOB_ID','manual')}.json").write_text(
    json.dumps(diagnostics,indent=2)+"\n")
if not (root/"selected-training.json").exists():
    if unfinished:
        print("No viable full configuration yet. The remaining gate will trigger selection again.",flush=True)
    else:
        print("No validated configuration fits the deadline and protected evaluation window.",flush=True)
