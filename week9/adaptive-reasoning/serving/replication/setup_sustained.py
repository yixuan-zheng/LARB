"""Build a sustained trace on the same questions for eight and sixteen slots."""
import json
from pathlib import Path

manifest = json.loads(Path("../replication.json").read_text())
rows = []
for block in manifest["blocks"][:2]:
    data = {row["question_id"]:row for row in block["questions"]}
    for key in block["arrival_orders"]["920011"]:
        row = dict(data[key])
        row["shuffle_mode"] = block["within_source_shuffles"]["71"][key]
        row["shuffle_modes"] = {
            seed:block["within_source_shuffles"][seed][key] for seed in ("151","411")
        }
        rows.append(row)
assert len(rows)==len({row["question_id"] for row in rows})==48
p=Path("freeze.json")
previous=json.loads(p.read_text())
previous.update(pilot_holdout=rows,traffic="sustained",interval_seconds=12,
                primary_shuffle_seed=71,secondary_shuffle_seed=151)
p.write_text(json.dumps(previous,indent=2)+"\n")

p=Path("pilot.py")
s=p.read_text().replace("len(questions) == 24","len(questions) == 48").replace("}) == 36","}) == 60")
p.write_text(s)
p=Path("replay.py")
s=p.read_text()
start=s.index("def rotated_arms():")
end=s.index("async def experiment",start)
s=s[:start]+'''def rotated_arms():
    arms = ("shuffle-load", "combined", "load", "task", "shuffle-load-151", "fixed4k", "fixed8k")
    if os.environ["SLOTS"]=="16":
        return arms[2:] + arms[:2]
    return arms


'''+s[end:]
s=s.replace('arrivals = [0.]*6 + [20.]*6','arrivals = [12.*i for i in range(12)]')
s=s.replace('pilot.questions,[0.]*12+[20.]*12,deadline,920000',
            'pilot.questions,[12.*i for i in range(len(pilot.questions))],deadline,920000')
s=s.replace('"mixed-burst"','"mixed-sustained"').replace('f"mixed-burst--','f"mixed-sustained--')
assert 'pilot.questions,[12.*i' in s
p.write_text(s)
p=Path("run.sbatch")
s=p.read_text().replace("--time=90","--time=03:30:00").replace("10s 83m","10s 203m")
p.write_text(s)
