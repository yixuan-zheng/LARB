"""Week 2 quality plots: transition quality on dev vs held-out, and quality vs measured goodput.

CPU only (matplotlib). Goodput comes from the mixed-serving harness and the chunk-check
replay, both on azure_conv_steady at rate scale 0.1 with the same SLO (TTFT <= 1 s, max ITL <= 200 ms):

  git show origin/mixed-serving:week2/mixed-serving/results/analysis/runs.csv > /tmp/serving_runs.csv
  git show origin/yixuan:week2/chunk-check/results/analysis/runs.csv > /tmp/chunk_runs.csv
  python plots.py --serving-runs /tmp/serving_runs.csv --chunk-runs /tmp/chunk_runs.csv
"""
import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[3]
WEEK1 = ROOT / "week1" / "quality" / "results"
OUT = ROOT / "week2" / "quality" / "results" / "plots"
DEV, HELDOUT = "gen-dev-20261001-205536", "gen-heldout-20261004-204404"
FLOOR = -5.0
INK, MUTED, GRID = "#0b0b0b", "#52514e", "#e4e3df"
BLUE, ORANGE, AQUA = "#2a78d6", "#eb6834", "#1baf7a"
ORDER = ["static_S", "LS_early", "LS_late", "SL_early", "SL_late", "alt16", "alt4"]


def read_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def quality(run_id):
    return {r["schedule"]: r for r in read_csv(WEEK1 / run_id / "quality_table.csv")}


def style(ax, grid_axis):
    ax.spines[["top", "right"]].set_visible(False)
    ax.spines[["left", "bottom"]].set_color(MUTED)
    ax.tick_params(colors=MUTED, labelsize=9)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def ci(row):
    d = float(row["delta_pp"])
    return d, [[d - float(row["delta_lo"])], [float(row["delta_hi"]) - d]]


def transition_quality():
    dev, held = quality(DEV), quality(HELDOUT)
    fig, ax = plt.subplots(figsize=(8, 4.6))
    for i, s in enumerate(ORDER):
        y = len(ORDER) - 1 - i
        d, err = ci(dev[s])
        ax.errorbar(d, y + 0.15, xerr=err, fmt="o", mfc="white", mec=MUTED, color=MUTED, ms=7,
                    capsize=3, elinewidth=1.5, label="dev" if i == 0 else None)
        if s in held:
            d, err = ci(held[s])
            ax.errorbar(d, y - 0.15, xerr=err, fmt="o", color=BLUE, ms=8, capsize=3, elinewidth=2,
                        label="held-out (run once)" if s == "static_S" else None)
            ax.annotate(held[s]["floor"], (float(held[s]["delta_hi"]), y - 0.15), xytext=(6, 0),
                        textcoords="offset points", va="center", fontsize=9, color=INK)
    ax.axvline(0, color=MUTED, linewidth=1)
    ax.axvline(FLOOR, color=INK, linestyle="--", linewidth=1.2)
    ax.annotate("floor −5 pp", (FLOOR, len(ORDER) - 0.5), xytext=(-4, 0), textcoords="offset points",
                ha="right", fontsize=8, color=INK)
    labels = [f"{s}\n{float(dev[s]['frac_switched']):.0%} switched · {float(dev[s]['frac_small']):.0%} Small"
              for s in ORDER]
    ax.set_yticks(range(len(ORDER)), labels[::-1], fontsize=8)
    ax.set_ylim(-0.6, len(ORDER) - 0.3)
    ax.set_xlabel("Accuracy vs static Large (pp), 95% paired bootstrap CI", fontsize=9, color=INK)
    style(ax, "x")
    ax.legend(frameon=False, fontsize=9, loc="lower right")
    fig.suptitle(f"Transition quality on GSM8K (n = 250 per split; static Large: dev "
                 f"{float(dev['static_L']['accuracy']):.1f}%, held-out {float(held['static_L']['accuracy']):.1f}%)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    path = OUT / "transition_quality_heldout.png"
    fig.savefig(path, dpi=200)
    return path


def goodput(rows):
    # SLO-meeting requests per second, computed the same way for both sources
    values = [float(r["attainment"]) * float(r["throughput_rps"]) for r in rows]
    return sum(values) / len(values), min(values), max(values), len(values)


def quality_vs_goodput(serving_csv, chunk_csv):
    held = quality(HELDOUT)
    serving = [r for r in read_csv(serving_csv) if r["trace"] == "azure_conv_steady" and float(r["rate_scale"]) == 0.1]
    chunk = read_csv(chunk_csv)
    points = [  # label, goodput rows, quality schedule, color, marker
        ("Large", [r for r in serving if r["policy"] == "static_large"], "static_L", BLUE, "o"),
        ("Small", [r for r in serving if r["policy"] == "static_small"], "static_S", ORANGE, "o"),
        ("Small prefill → Large decode", [r for r in serving if r["policy"] == "phase_hybrid"], "SL_early", AQUA, "o"),
        ("Large, 512-token chunks", [r for r in chunk if r["configuration"] == "large_chunk512"], "static_L", BLUE, "s"),
        ("hybrid, 512-token chunks", [r for r in chunk if r["configuration"] == "hybrid_chunk512"], "SL_early", AQUA, "s"),
    ]
    fig, ax = plt.subplots(figsize=(8, 4.4))
    for label, rows, schedule, color, marker in points:
        mean, lo, hi, n = goodput(rows)
        d, err = ci(held[schedule])
        ax.errorbar(mean, d, xerr=[[mean - lo], [hi - mean]], yerr=err, fmt=marker, color=color, ms=8,
                    capsize=3, elinewidth=1.5, zorder=3)
        # below the floor line the label goes underneath so it doesn't sit on the line
        ax.annotate(label, (mean, d), xytext=(8, -12 if d < FLOOR else 6), textcoords="offset points",
                    fontsize=8, color=INK)
    ax.axhline(FLOOR, color=INK, linestyle="--", linewidth=1.2, zorder=1)
    ax.annotate("quality floor −5 pp", (ax.get_xlim()[1], FLOOR), xytext=(-4, 4), textcoords="offset points",
                ha="right", fontsize=8, color=INK)
    ax.axhline(0, color=GRID, linewidth=1.2, zorder=1)
    ax.set_xlabel("Measured goodput (SLO-meeting requests/s), mean and range over 3 runs", fontsize=9, color=INK)
    ax.set_ylabel("Held-out accuracy vs Large (pp), 95% CI", fontsize=9, color=INK)
    style(ax, "y")
    fig.suptitle("Quality vs measured goodput (azure_conv_steady, rate 0.1; ● original scheduling, ■ chunked prefill)",
                 fontsize=10, color=INK, x=0.01, ha="left")
    fig.tight_layout()
    path = OUT / "quality_vs_goodput.png"
    fig.savefig(path, dpi=200)
    return path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--serving-runs", required=True)
    parser.add_argument("--chunk-runs", required=True)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    print("wrote", transition_quality())
    print("wrote", quality_vs_goodput(args.serving_runs, args.chunk_runs))


if __name__ == "__main__":
    main()
