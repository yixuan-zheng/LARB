import json
from pathlib import Path
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

root = Path(__file__).resolve().parent.parent
out = root / "results"
r = json.loads((out / "analysis.json").read_text())
policies = ["large", "small", "request", "iteration"]
labels = ["Large", "Small", "Request-level", "Iteration-level"]
colors = ["#4c78a8", "#f58518", "#54a24b", "#b279a2"]
fig, axes = plt.subplots(1, 2, figsize=(11, 4), layout="constrained")
for i, (policy, label, color) in enumerate(zip(policies, labels, colors)):
    v = r["policy_aggregate"].get(policy)
    if not v:
        continue
    axes[0].bar(i, v["goodput"], color=color)
    xs = [x["goodput"] for x in r["per_trace"] if x["policy"] == policy]
    axes[0].scatter([i] * len(xs), xs, color="black", s=18, zorder=3)
    axes[1].bar(i, 100 * v["slo_pass_rate"], color=color)
for ax in axes:
    ax.set_xticks(range(4), labels, rotation=15)
    ax.spines[["top", "right"]].set_visible(False)
axes[0].set_ylabel("Correct, SLO-compliant answers / second")
axes[0].set_title("Bars: pooled replay; dots: individual traces")
axes[1].set_ylabel("Requests satisfying latency SLOs (%)")
axes[1].set_ylim(0, 100)
axes[1].set_title("TTFT ≤1 s; max inter-token gap ≤200 ms")
fig.suptitle("Gemma 3n decode-policy pilot — cohort replay, not continuous batching")
fig.savefig(out / "policy_comparison.png", dpi=180)
fig.savefig(out / "policy_comparison.pdf")
plt.close(fig)
fig, axes = plt.subplots(2, 1, figsize=(10, 6), layout="constrained")
for policy, label, color in zip(policies, labels, colors):
    p = out / f"replay_11_{policy}.json"
    if not p.exists():
        continue
    v = json.loads(p.read_text())
    ops = v["operations"]
    requests = v["requests"]
    axes[0].step(
        [x["start_s"] for x in ops],
        [x["pending_before"] for x in ops],
        where="post",
        label=label,
        color=color,
    )
    axes[1].scatter(
        [x["arrival_s"] for x in requests],
        [x["ttft_ms"] for x in requests],
        s=12,
        alpha=0.7,
        label=label,
        color=color,
    )
axes[0].set_ylabel("Waiting requests at cohort admission")
axes[0].legend(ncol=4)
axes[1].axhline(1000, color="black", linestyle="--", label="TTFT SLO")
axes[1].set_ylabel("TTFT (ms)")
axes[1].set_xlabel("Time from replay start / request arrival (s)")
fig.suptitle("Trace 11: observed queue pressure and TTFT")
fig.savefig(out / "queue_latency.png", dpi=180)
plt.close(fig)
