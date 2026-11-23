"""Collect timing-valid arm summaries and paired deadline transitions."""
import json
from pathlib import Path

root = Path.cwd()
fields = ("arm", "planned", "correct_on_time", "correct", "goodput_per_minute",
          "total_output_tokens", "p95_latency_s", "cuts", "binding_cuts")
blocks = []
rankings = {}
for line in (root/"followup-jobs.tsv").read_text().splitlines():
    kind,slots,block,job = line.split()
    stage = root/f"{kind}-{slots}-{block}"/f"evidence-{job}"
    summary = stage/"pilot-summary.json"
    record = dict(kind=kind,slots=int(slots),block=int(block),job=job,arms=[],paired=[])
    if summary.exists():
        by_arm = {}
        if kind == "shuffle":
            prior_job = (root/f"four-{block}"/"job-id").read_text().strip()
            prior = root/f"four-{block}"/f"evidence-{prior_job}"
            trace = Path("traces/mixed-burst.jsonl")
            if (stage/trace).read_bytes() == (prior/trace).read_bytes():
                for arm in ("combined","shuffle-load"):
                    valid = prior/"validity"/f"mixed-burst-{arm}.json"
                    if not json.loads(valid.read_text())["valid"]:
                        continue
                    scored = json.loads((prior/"scored"/f"mixed-burst-{arm}.json").read_text())
                    row = scored["summary"]
                    record["arms"].append({**{key:row.get(key) for key in fields},"archived_job":prior_job})
                    by_arm[arm] = {r["question_id"]:r for r in scored["rows"]}
                    rankings.setdefault((kind,slots,arm),[]).append(row)
        for row in json.loads(summary.read_text()):
            arm = row["arm"]
            if not json.loads((stage/"validity"/f"mixed-burst-{arm}.json").read_text())["valid"]:
                continue
            record["arms"].append({key:row.get(key) for key in fields})
            scored = stage/"scored"/f"mixed-burst-{arm}.json"
            by_arm[arm] = {x["question_id"]:x for x in json.loads(scored.read_text())["rows"]}
            group = rankings.setdefault((kind,slots,arm),[])
            group.append(row)
        pairs = [("slack","combined"),("slack-margin","slack")]
        pairs.extend((arm,"combined") for arm in by_arm if arm.startswith("shuffle-load"))
        for arm,control in pairs:
            if arm not in by_arm or control not in by_arm:
                continue
            x,y = by_arm[arm],by_arm[control]
            assert x.keys() == y.keys()
            record["paired"].append(dict(arm=arm,control=control,
                rescued=sum(x[k]["good"] and y[k]["correct"] and not y[k]["good"] for k in x),
                gained=sum(x[k]["good"] and not y[k]["good"] for k in x),
                lost=sum(y[k]["good"] and not x[k]["good"] for k in x)))
    blocks.append(record)
totals = [dict(kind=kind,slots=int(slots),arm=arm,blocks=len(rows),
    **{key:sum(row[key] for row in rows) for key in ("planned","correct_on_time","correct","total_output_tokens")})
    for (kind,slots,arm),rows in sorted(rankings.items())]
paired_totals = {}
for block in blocks:
    for entry in block["paired"]:
        key = (block["kind"],block["slots"],entry["arm"],entry["control"])
        acc = paired_totals.setdefault(key,dict(kind=key[0],slots=key[1],arm=key[2],
            control=key[3],blocks=0,rescued=0,gained=0,lost=0))
        acc["blocks"] += 1
        for metric in ("rescued","gained","lost"):
            acc[metric] += entry[metric]
report = dict(blocks=blocks, totals=totals, paired_totals=list(paired_totals.values()))
(root/"followup-report.json").write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps(report))
