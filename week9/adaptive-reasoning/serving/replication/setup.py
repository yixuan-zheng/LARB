"""Build a slot-specific replay from the validated combined pilot."""
import json
import os
from pathlib import Path

root = Path.cwd()
prepared = json.loads((root.parent / "replication.json").read_text())
block_id = int(os.environ["BLOCK_ID"])
slots = int(os.environ["SLOTS"])
block = prepared["blocks"][block_id]
seed = (71,151,411)[block_id]
orders = block["arrival_orders"]
order = orders["920011" if slots == 4 else "920087" if block_id == 2 else "920011"]
by_key = {r["question_id"]:r for r in block["questions"]}
prior = json.loads((root / "pilot-freeze.json").read_text())
rows = [dict(by_key[key],shuffle_mode=block["within_source_shuffles"][str(seed)][key]) for key in order]
Path("freeze.json").write_text(json.dumps(dict(pilot_holdout=rows,calibration=prior["calibration"],
    block=block["name"],slots=slots,shuffle_seed=seed,arrival_order=order),indent=2)+"\n")

p = Path("pilot.py")
s = p.read_text().replace("len(questions) == 12","len(questions) == 24").replace("}) == 24","}) == 36")
s = s.replace("    raw = analysis.load_requests(out)\n    scored =", """    raw = analysis.load_requests(out)
    from cuts import reconcile
    cut_audit = reconcile(raw, (analysis.runtime_key(name,arm,row) for row in rows), out/"worker.jsonl")
    config.write_json(out/"cut-audit"/f"{name}-{arm}.json",cut_audit)
    scored =""")
s = s.replace('    summary["observation_s"]', '    summary.update(cut_audit)\n    summary["observation_s"]',1)
p.write_text(s)
p = Path("replay.py")
s = p.read_text()
s = s.replace('pilot.questions,arrivals,deadline,920000','pilot.questions,[0.]*12+[20.]*12,deadline,920000')
s = s.replace('for arm in ("combined", "load", "shuffle-load", "task", "fixed8k", "fixed4k"):',
'''for arm in rotated_arms():''')
fragment = '''def rotated_arms():
    arms = ("combined", "load", "shuffle-load", "task", "fixed8k", "fixed4k")
    offset = 2 * int(os.environ["BLOCK_ID"])
    if os.environ["SLOTS"] == "8":
        offset += 1
    return arms[offset:] + arms[:offset]


'''
s = s.replace("async def experiment(server):",fragment+"async def experiment(server):")
p.write_text(s)
assert "[0.]*12+[20.]*12" in s and "for arm in rotated_arms()" in s
