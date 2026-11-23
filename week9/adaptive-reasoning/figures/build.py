"""Regenerate closeout CSV and presentation figures from the compact archive."""
import csv
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
results = root / "results/closeout"
data = json.loads((results / "evidence.json").read_text())
entries = []
for name, run in data["serving"].items():
    for row in run["summaries"]:
        phase = row["phase"]
        assert run["validity"][phase]["valid"]
        records = run["scored_rows"][phase]
        n = row["planned"]
        assert n == len(records)
        assert row["correct_on_time"] == sum(r["good"] for r in records)
        assert row["correct"] == sum(r["correct"] for r in records)
        assert row["total_output_tokens"] == sum(r["output_tokens"] for r in records)
        condition = row["condition"]
        trace = run["traces"][condition]
        slots = 16 if name == "sustained-16" else 4 if name.startswith(
            ("four","recover-4","shuffle-4","pilot")) else 8
        entries.append(dict(run=name,job=run["job"],gpu="L40S",slots=slots,
            deadline_s=trace[0]["deadline_s"],arrival_offsets_s=json.dumps([r["arrival_s"] for r in trace]),
            first_generation_seed=trace[0]["seed"],arm=row["arm"],n=n,
            correct_on_time=row["correct_on_time"],goodput_per_minute=row["goodput_per_minute"],
            eventually_correct=row["correct"],eventual_accuracy=row["accuracy"],
            output_tokens=row["total_output_tokens"],mean_output_tokens=row["total_output_tokens"]/n,
            prompt_tokens=row.get("total_prompt_tokens"),mean_queue_s=row["mean_queue_s"],
            mean_latency_s=row["mean_latency_s"],p50_latency_s=row["p50_latency_s"],
            p95_latency_s=row.get("p95_latency_s"),short_cap_admissions=row.get("short_admissions"),
            # The pilot shuffle has one omitted worker event verified in the
            # archived logs. The cut was nonbinding.
            logged_cuts=1 if name=="pilot" and row["arm"]=="shuffle-load" else row["cuts"],
            binding_cuts=0 if name=="pilot" and row["arm"]=="shuffle-load" else row.get("binding_cuts")))
with (results / "live.csv").open("w",newline="") as stream:
    writer=csv.DictWriter(stream,fieldnames=list(entries[0]),lineterminator="\n")
    writer.writeheader()
    writer.writerows(entries)

# Preserve within-job paired contrasts, and explicitly label separate-allocation
# comparisons only when the emitted trace matches exactly.
comparisons = []
for name, run in data["serving"].items():
    reference_name = {"coin-final":"eight-0","pilot-combined":"pilot"}.get(name,name)
    control_run = data["serving"][reference_name]
    if run["traces"].get("mixed-burst") != control_run["traces"].get("mixed-burst"):
        continue
    for row in run["summaries"]:
        arm = row["arm"]
        if arm != "combined" and not arm.startswith("coin"):
            continue
        for ctl in control_run["summaries"]:
            if ctl["arm"] not in {"fixed4k","fixed8k","task","load","shuffle-load","combined"} or ctl["arm"] == arm:
                continue
            if row["condition"] != ctl["condition"]:
                continue
            x={r["question_id"]:r for r in run["scored_rows"][row["phase"]]}
            y={r["question_id"]:r for r in control_run["scored_rows"][ctl["phase"]]}
            assert x.keys()==y.keys()
            gains=sum(x[q]["good"] and not y[q]["good"] for q in x)
            losses=sum(y[q]["good"] and not x[q]["good"] for q in x)
            accuracy_points=100*(row["correct"]-ctl["correct"])/len(x)
            relative_gain=(row["goodput_per_minute"]/ctl["goodput_per_minute"]-1
                           if ctl["goodput_per_minute"] else None)
            comparisons.append(dict(run=name,control_run=reference_name,arm=arm,control=ctl["arm"],
                n=len(x),on_time_gained=gains,on_time_lost=losses,
                eventual_accuracy_delta_pp=accuracy_points,relative_goodput_gain=relative_gain,
                point_criterion_met=relative_gain is not None and relative_gain>=.05-1e-12
                and accuracy_points>=-2-1e-12))
with (results/"paired.csv").open("w",newline="") as stream:
    writer=csv.DictWriter(stream,fieldnames=list(comparisons[0]),lineterminator="\n")
    writer.writeheader()
    writer.writerows(comparisons)

if __name__ == "__main__":
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"svg.hashsalt":"larb-closeout","font.family":"DejaVu Sans","axes.spines.top":False,
                         "axes.spines.right":False,"axes.titleweight":"bold","font.size":11})
    blue,gray,teal="#28538B","#718096","#168070"

    def save(fig,name):
        fig.tight_layout()
        path = root/"figures"/f"{name}.svg"
        fig.savefig(path,metadata={"Date":None})
        path.write_text("\n".join(line.rstrip() for line in path.read_text().splitlines())+"\n")
        plt.close(fig)

    offline=data["offline"]["coin_offline"]
    fig,ax=plt.subplots(figsize=(8,4.5))
    for key,label,c,offset in [
        ("fixed_medium","Fixed Medium",gray,(5,-15)),("fixed_high","Fixed High",gray,(-92,7)),
        ("global_expected","Global coin",teal,(-50,-24)),("within_source_shuffle","Within-source shuffle",gray,(4,11)),
        ("learned","Learned routing",blue,(5,-16))]:
        item=offline[key]
        x=item["tokens"]+(offline["router_prefill_tokens"] if key=="learned" else 0)
        y=100*item["accuracy"]
        ax.scatter(x,y,color=c,s=70)
        ax.annotate(label,(x,y),xytext=offset,textcoords="offset points")
    ax.set(xlabel="Mean charged tokens per request",ylabel="Accuracy (%)",title="Held-out accuracy and compute · 96 questions",
           xlim=(1500,4200),ylim=(70,84))
    save(fig,"offline-frontier")

    evaluation=data["training"]["7281434"]["evaluation"]
    pairs=[(0,1),(1,0),(1,1),(0,0)]
    counts=[sum(tuple(int(a["correct"]) for a in r["arms"][1:])==pair for r in evaluation) for pair in pairs]
    high=[sum(r["selected"]==2 and tuple(int(a["correct"]) for a in r["arms"][1:])==pair
              for r in evaluation) for pair in pairs]
    fig,ax=plt.subplots(figsize=(8,4.5))
    labels=["Only High correct","Only Medium correct","Both correct","Neither correct"]
    ax.barh(labels,counts,color="#DCE5EF",label="All questions")
    ax.barh(labels,high,color=blue,label="Routed to High")
    for i,(n,h) in enumerate(zip(counts,high)):
        ax.text(n+.7,i,f"{h}/{n}",va="center")
    ax.set(xlabel="Questions",title="Where High was assigned",xlim=(0,76))
    ax.invert_yaxis()
    ax.legend(loc="lower right")
    save(fig,"allocation-opportunity")

    def panel(run,arms,labels,title,name):
        lookup={r["arm"]:r for r in entries if r["run"]==run}
        fig,axes=plt.subplots(1,2,figsize=(10,4.8))
        colors=[teal if "Coin +" in label else blue if label=="Combined" else gray for label in labels]
        for ax,key,xlabel in zip(axes,("goodput_per_minute","output_tokens"),
                                ("Correct on time / minute","Output tokens (thousands)")):
            vals=[lookup[a][key]/(1000 if key=="output_tokens" else 1) for a in arms]
            ax.barh(labels,vals,color=colors)
            pad=max(vals)*.025
            ax.set(xlabel=xlabel,xlim=(0,max(vals)*1.18))
            ax.invert_yaxis()
            for i,v in enumerate(vals):
                ax.text(v+pad,i,f"{v:.2f}" if key=="goodput_per_minute" else f"{v:.1f}",va="center")
        axes[1].tick_params(labelleft=False)
        fig.suptitle(title,fontweight="bold")
        save(fig,name)

    panel("sustained-8",["combined","shuffle-load-151","task","load","fixed4k","fixed8k"],
          ["Combined","Shuffle + load (151)","Task-only","Load-only","Fixed 4K","Fixed 8K"],
          "Sustained traffic · 48 requests, 8 slots","sustained-eight")
    panel("coin-final",["coin-151","coin-load-151","coin-411","coin-load-411"],
          ["Coin 151","Coin + load 151","Coin 411","Coin + load 411"],
          "Final burst · 24 requests, 8 slots","probabilistic-live")
