"""Week 1 quality plots: quality vs measured latency, and transition-quality behavior.

CPU only (matplotlib, no torch). The latency numbers are the measured
end-to-end results from the latency-baselines branch:

  git show origin/latency-baselines:week1/latency-baselines/results/s4_end_to_end.csv > /tmp/s4_end_to_end.csv
  python plots.py --latency-csv /tmp/s4_end_to_end.csv
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

RESULTS = Path(__file__).resolve().parents[1] / "results"
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
# fixed categorical order from the reference palette; markers keep lines apart without color
SERIES = {
    "LS_early": ("#2a78d6", "o"), "LS_late": ("#eb6834", "s"), "SL_early": ("#1baf7a", "^"),
    "SL_late": ("#eda100", "D"), "alt16": ("#e87ba4", "v"), "alt4": ("#008300", "P"),
}
STATIC = {"static_L": ("large", "Large", "#2a78d6"), "static_S": ("small", "Small", "#eb6834")}
BUCKETS = ["1", "2-8", "9-32", ">32"]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def style(ax):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis="y", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def quality_vs_latency(run_id, latency_csv, grid, out_dir):
    table = {r["schedule"]: r for r in read_csv(RESULTS / run_id / "quality_table.csv")}
    latency = {r["preset"]: r for r in read_csv(latency_csv) if r["grid"] == grid}
    split = table["static_L"]["split"]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6), sharey=True)
    for ax, (column, label) in zip(axes, [("ttft_ms_median", "Time to first token (ms, median)"),
                                          ("itl_ms_median", "Inter-token latency (ms, median)")]):
        for schedule, (preset, name, color) in STATIC.items():
            row = table[schedule]
            x, y = float(latency[preset][column]), float(row["accuracy"])
            err = [[y - float(row["acc_lo"])], [float(row["acc_hi"]) - y]]
            ax.errorbar(x, y, yerr=err, fmt="o", color=color, ms=8, capsize=4, elinewidth=1.5, label=name)
            ax.annotate(f"{name} {y:.1f}%", (x, y), xytext=(9, 0), textcoords="offset points",
                        va="center", fontsize=9, color=INK)
        speedup = 100 * (1 - float(latency["small"][column]) / float(latency["large"][column]))
        ax.set_title(f"Small is {speedup:.1f}% faster", fontsize=9, color=MUTED, loc="left")
        ax.set_xlabel(label, fontsize=9, color=INK)
        ax.margins(x=0.35)
        style(ax)
    axes[0].set_ylabel("GSM8K accuracy (%), 95% CI", fontsize=9, color=INK)
    axes[1].legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle(f"Quality vs measured latency ({split}, n={table['static_L']['n']}; "
                 f"latency: batch 8, ~1k-token prompt, L40S)", fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    path = out_dir / f"quality_vs_latency_{split}.png"
    fig.savefig(path, dpi=200)
    return path


def bucket_means(rows, metric):
    """Mean per bucket, pooling the widths of a schedule by their number of steps."""
    means = []
    for b in BUCKETS:
        picked = [r for r in rows if r["bucket"] == b]
        steps = sum(int(r["n_steps"]) for r in picked)
        means.append(sum(float(r[metric]) * int(r["n_steps"]) for r in picked) / steps if steps else None)
    return means


def transition_quality(diag_run_id, out_dir):
    summary = read_csv(RESULTS / diag_run_id / "diagnostics_summary.csv")
    gold = json.loads((RESULTS / diag_run_id / "manifest.json").read_text())["full_prefix_gold_nll"]
    gap = gold["small"] - gold["large"]
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    xs = range(len(BUCKETS))
    for ax, metric, label, title in [
        (axes[0], "js_fixed", "JS divergence", "How far predictions move vs uniform history"),
        (axes[1], "dnll_fixed", "Gold-token ΔNLL (nats)", "Effect on the correct token (+ = history hurts)"),
    ]:
        for schedule, (color, marker) in SERIES.items():
            ys = bucket_means([r for r in summary if r["schedule"] == schedule], metric)
            ax.plot(xs, [float("nan") if y is None else y for y in ys], color=color, marker=marker,
                    ms=6, linewidth=1.5, label=schedule)
        if metric == "js_fixed":
            drift = bucket_means(summary, "js_drift")
            ax.plot(xs, drift, color=MUTED, linestyle="--", linewidth=1.5, label="bf16 drift (noise)")
        else:
            ax.axhline(0, color=MUTED, linewidth=1)
            for sign in (1, -1):
                ax.axhline(sign * gap, color=MUTED, linestyle=":", linewidth=1.2)
            ax.annotate(f"±Large–Small gap per token ({gap:.3f})", (len(BUCKETS) - 1, gap), xytext=(0, 4),
                        textcoords="offset points", ha="right", fontsize=8, color=MUTED)
        ax.set_xticks(list(xs), BUCKETS)
        ax.set_xlabel("Steps since the last switch", fontsize=9, color=INK)
        ax.set_ylabel(label, fontsize=9, color=INK)
        ax.set_title(title, fontsize=9, color=MUTED, loc="left")
        style(ax)
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, loc="lower center", ncol=7, frameon=False, fontsize=8)
    fig.suptitle("Retained-cache history after a switch (teacher-forced gold solutions, 50 dev questions)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    path = out_dir / "transition_quality.png"
    fig.savefig(path, dpi=200)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--latency-csv", required=True)
    parser.add_argument("--run-id", default="gen-dev-20261001-205536")
    parser.add_argument("--diag-run-id", default="diag-dev-20261002-134051")
    parser.add_argument("--grid", default="L1024_B8")  # closest measured cell to the GSM8K runs
    args = parser.parse_args()
    out_dir = RESULTS / "plots"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("wrote", quality_vs_latency(args.run_id, args.latency_csv, args.grid, out_dir))
    print("wrote", transition_quality(args.diag_run_id, out_dir))


if __name__ == "__main__":
    main()
