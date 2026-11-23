"""CPU audit of paired Medium/High continuations from the mixed workload."""
import json
import statistics
import sys
from collections import Counter
from pathlib import Path

rows = [json.loads(line) for line in Path(sys.argv[1]).read_text().splitlines()]
assert len(rows) == len({r["question_id"] for r in rows}) == 96
counts = Counter()
groups = {}
for row in rows:
    m, h = row["arms"][1:]
    assert row["selected"] in (1, 2)
    result = f"{int(m['correct'])}{int(h['correct'])}"
    counts[result] += 1
    if row["selected"] == 2:
        counts["selected_"+result] += 1
    groups.setdefault(row["stratum"], []).append((row,m,h,result))

by_source = {}
for source, group in groups.items():
    high = sum(r["selected"] == 2 for r, *_ in group)
    rate = high / len(group)
    by_source[source] = dict(n=len(group), high=high,
        outcomes=dict(Counter(result for _,_,_,result in group)),
        selected_outcomes=dict(Counter(result for r,_,_,result in group if r["selected"]==2)),
        shuffled_high_only=rate*sum(result=="01" for _,_,_,result in group),
        shuffled_medium_only=rate*sum(result=="10" for _,_,_,result in group))

flat = [x for group in groups.values() for x in group]
early = {}
for label, subset in (
        ("all",flat),("selected_high",[x for x in flat if x[0]["selected"]==2]),
        ("high_without_correctness_gain",[x for x in flat if x[0]["selected"]==2 and x[3]!="01"])):
    deltas = [h["total_tokens"]-m["total_tokens"] for _,m,h,_ in subset]
    generated_upper = [h["total_tokens"]-r["route_prefill_tokens"] for r,_,h,_ in subset]
    early[label] = dict(n=len(subset), high_tokens_le_medium=sum(x<=0 for x in deltas),
        high_tokens_below_medium_cap=sum(t<2048 for t in generated_upper),
        high_tokens_below_high_cap=sum(t<8192 for t in generated_upper),
        mean_extra_high_tokens=statistics.mean(deltas), net_extra_high_tokens=sum(deltas))
print(json.dumps(dict(counts=counts,by_source=by_source,realized_cost=early),indent=2))
