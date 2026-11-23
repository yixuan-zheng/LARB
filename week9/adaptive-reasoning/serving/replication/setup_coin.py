"""Add independent per-arrival Bernoulli controls to the frozen burst."""
import json
import random
from pathlib import Path

path = Path("freeze.json")
data = json.loads(path.read_text())
seeds = (151, 411)
for field in ("pilot_holdout", "calibration"):
    for seed in seeds:
        rng = random.Random(seed)
        for row in data[field]:
            row[f"coin_{seed}"] = 2 if rng.random() < .4 else 1
data["coin_high_probability"] = .4
data["coin_seeds"] = list(seeds)
path.write_text(json.dumps(data,indent=2)+"\n")

path = Path("routed_contract.py")
s = path.read_text()
anchor = "def choose(arm, question, pressure):"
assert s.count(anchor) == 1
s = s.replace(anchor, """COIN_ARMS = ("coin-151", "coin-load-151", "coin-load-411", "coin-411")
ARMS = (*ARMS, *COIN_ARMS)


def choose(arm, question, pressure):
    if arm in COIN_ARMS:
        seed = arm.rsplit("-", 1)[-1]
        mode = question[f"coin_{seed}"]
        live = arm.startswith("coin-load-")
        cap = 2048 if mode == 1 else 4096 if live and pressure else 8192
        return mode, cap, live""")
path.write_text(s)
path = Path("replay.py")
s = path.read_text()
start,end = s.index("def rotated_arms():"),s.index("async def experiment")
path.write_text(s[:start]+'''def rotated_arms():
    return ("coin-151", "coin-load-151", "coin-load-411", "coin-411")


'''+s[end:])
