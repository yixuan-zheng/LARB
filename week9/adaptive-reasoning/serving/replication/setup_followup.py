"""Prepare missing-block recovery, alternative shuffles, and coordination arms."""
import json
import os
from pathlib import Path

kind = os.environ["KIND"]
block = int(os.environ["BLOCK_ID"])
data = json.loads(Path("../replication.json").read_text())
freeze = Path("freeze.json")
manifest = json.loads(freeze.read_text())
source = data["blocks"][block]
all_seeds = list(source["within_source_shuffles"])
primary = str(manifest["shuffle_seed"])
extra = [seed for seed in all_seeds if seed != primary]
for row in manifest["pilot_holdout"]:
    row["shuffle_modes"] = {seed: source["within_source_shuffles"][seed][row["question_id"]]
                            for seed in all_seeds}
for row in manifest["calibration"]:
    row["shuffle_modes"] = {seed: row["shuffle_mode"] for seed in all_seeds}
freeze.write_text(json.dumps(manifest,indent=2)+"\n")

p = Path("replay.py")
s = p.read_text()
start = s.index("def rotated_arms():")
end = s.index("async def experiment",start)
if kind=="recovery":
    arms = ("combined","shuffle-load","load","task","fixed4k","fixed8k")
elif kind=="shuffle":
    arms = tuple(f"shuffle-load-{seed}" for seed in extra)
else:
    arms = ("combined","slack","slack-margin","shuffle-load",*(f"shuffle-load-{seed}" for seed in extra))
    if block == 1:
        arms = arms[3:] + arms[:3]
p.write_text(s[:start] + f"def rotated_arms():\n    return {arms!r}\n\n\n" + s[end:])

p = Path("pilot.py")
s = p.read_text()
assert s.count("drain_allowance_s=1000")==1
p.write_text(s.replace("drain_allowance_s=1000","drain_allowance_s=1900"))
p = Path("replay.py")
s = p.read_text()
p.write_text(s.replace("ClientTimeout(total=1500)","ClientTimeout(total=2400)"))
p = Path("run.sbatch")
s = p.read_text()
start = s.index('if [[ "$SLOTS" == 8 ]]; then')
end = s.index('\nfi',start)+3
s = s[:start]+s[end:]
if kind=="recovery" and os.environ["SLOTS"]=="8":
    s=s.replace('base="$HOME', '''control="../recover-4-2"
job=$(cat "$control/job-id")
test -s "$control/evidence-$job/pilot-summary.json" || { echo "No scored 4-slot recovery results"; exit 1; }
base="$HOME''',1)
wall = {"recovery":185 if os.environ["SLOTS"]=="4" else 135, "shuffle":90, "coord":140}[kind]
s=s.replace("--time=02:30:00",f"--time={wall}").replace("10s 143m",f"10s {wall-7}m")
if kind=="coord":
    s=s.replace('timeout --kill-after', '''export REPLICATION_ROOT="$(dirname "$PILOT_ROOT")"
export MARGIN_OUTPUT="$temp/margins.json"
timeout 10m "$base/vllm-proof-env/bin/python" -u cache_margins.py
export LARB_MARGIN_FILE="$MARGIN_OUTPUT"
timeout --kill-after''')
p.write_text(s)

p = Path("routed_contract.py")
s = p.read_text().replace('def choose(arm, question, pressure):',
    f'ARMS = (*ARMS, "slack", "slack-margin", *[f"shuffle-load-{{seed}}" for seed in {all_seeds!r}])\n\n\ndef choose(arm, question, pressure):')
s = s.replace('live = arm in ("load", "combined", "shuffle-load")',
              'live = arm in ("load", "combined", "slack", "slack-margin") or arm.startswith("shuffle-load")')
s = s.replace('    elif arm in ("task", "combined"):', '''    elif arm.startswith("shuffle-load-"):
        mode = question["shuffle_modes"][arm.removeprefix("shuffle-load-")]
    elif arm in ("task", "combined", "slack", "slack-margin"):''')
p.write_text(s)
if kind != "coord":
    raise SystemExit(0)

p = Path("repo/week7/scaled-serving/code/larb_scaled/server.py")
s=p.read_text()
s=s.replace("ADAPTER = None","ADAPTER = None\nMARGINS = {}")
s=s.replace('arrival_ts=time.monotonic(),','''arrival_ts=time.monotonic(),
        scheduled_deadline=float(body["scheduled"])+float(body["deadline_s"]),
        victim_strategy=ARM if ARM in ("slack", "slack-margin") else "remaining",
        preference_margin=MARGINS.get(question_id, {}).get("high_minus_medium_logprob"),''')
s=s.replace('    ADAPTER = LoRARequest(','''    margin_path = os.environ.get("LARB_MARGIN_FILE")
    if margin_path:
        MARGINS.update(json.loads(Path(margin_path).read_text()))
    ADAPTER = LoRARequest(''')
p.write_text(s)
p = p.with_name("controller.py")
s=p.read_text()
s=s.replace("from .contract import", "from coordination import choose as choose_coordinated\nfrom .policy import eligible\nfrom .contract import")
s=s.replace("                self.rows[row] = state",'''                state.scheduled_deadline = data.get("scheduled_deadline")
                state.victim_strategy = data.get("victim_strategy", "remaining")
                state.preference_margin = data.get("preference_margin")
                self.rows[row] = state''',1)
s=s.replace('            victim = choose_victim(states)','''            strategy = states[0].victim_strategy
            if strategy == "remaining":
                victim = choose_victim(states)
            else:
                now = time.monotonic()
                rows = []
                for state in states:
                    if not eligible(state):
                        continue
                    remaining = state.budget - len(state.output)
                    shortened = max(0,CUT_TARGET-len(state.output))
                    if strategy == "slack-margin" and state.preference_margin is None:
                        raise RuntimeError(f"Missing cached preference margin for {state.key}")
                    rows.append(dict(key=state.key,state=state,deadline=state.scheduled_deadline,
                                     arrival=state.arrival_ts,now=now,remaining_budget=remaining,
                                     estimated_remaining_seconds=(remaining+384)/20,
                                     estimated_short_seconds=(shortened+384)/20,
                                     high_minus_medium_logprob=state.preference_margin or 0.))
                chosen = choose_coordinated(rows,strategy=strategy)
                victim = chosen["state"] if chosen else None
                if chosen:
                    emit("worker","coordination_choice",strategy=strategy,key=victim.key,
                         **{key:value for key,value in chosen.items() if key not in ("state","key")})''')
p.write_text(s)
