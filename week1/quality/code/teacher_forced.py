"""Teacher-forced history diagnostics on the 50 diagnostic examples.

The gold solution is fed under each mixed schedule, so every schedule sees the
same tokens and only the width history differs. Steps match schedules.py: step 0
reads the prompt and predicts solution[0], step t reads solution[t-1] and
predicts solution[t]. At every step the mixed run is compared with two
references at that step's width:
  fixed  same chunks, all at that width (only the history differs)
  full   one uncached forward of the whole prefix at that width (the recompute
         counterfactual; not a free serving operation)
"drift" compares the two references, i.e. the usual bf16 cache-vs-recompute noise.

  python teacher_forced.py --limit 2      # smoke test
  python teacher_forced.py
"""
import argparse
import csv
import json
import math
from statistics import fmean

import torch

from common import RESULTS, load_model, new_run_id, patch_widths, run_manifest, select, write_json
from run_generation import FEWSHOT, load_examples
from schedules import SCHEDULES, run_lengths

SEED = 6222
MIXED = ["LS_early", "LS_late", "SL_early", "SL_late", "alt16", "alt4"]
BUCKETS = ["before", "1", "2-8", "9-32", ">32"]
METRICS = [f"{metric}_{ref}" for ref in ("fixed", "full", "drift") for metric in ("js", "top1", "dnll")]


def run_chunks(model, layers, prompt, solution, chunks):
    """Logits predicting solution[t] at every step t; each [preset, n_steps] chunk is one cached forward."""
    inputs = torch.cat([prompt, solution[:-1]])
    logits, cache, start = [], None, 0
    for preset, n in chunks:
        select(layers, preset)
        # step 0 reads the whole prompt, step t >= 1 reads solution[t - 1]
        lo = 0 if start == 0 else len(prompt) + start - 1
        hi = len(prompt) + start + n - 1
        out = model(input_ids=inputs[None, lo:hi], past_key_values=cache, use_cache=True, logits_to_keep=n)
        logits.append(out.logits[0])
        cache, start = out.past_key_values, start + n
    return torch.cat(logits)


def compare(a, b, gold):
    """Per-step JS divergence, top-1 agreement, and gold-token NLL of a minus NLL of b."""
    la, lb = a.float().log_softmax(-1), b.float().log_softmax(-1)
    log_m = torch.logaddexp(la, lb) - math.log(2)
    js = 0.5 * (la.exp() * (la - log_m)).sum(-1) + 0.5 * (lb.exp() * (lb - log_m)).sum(-1)
    top1 = la.argmax(-1) == lb.argmax(-1)
    dnll = (lb.gather(-1, gold[:, None]) - la.gather(-1, gold[:, None]))[:, 0]
    return js, top1, dnll


def steps_since_switch(widths):
    """1 at the first step after a switch, 2 at the next, ...; None before any switch."""
    since, last = [], None
    for t, width in enumerate(widths):
        if t and width != widths[t - 1]:
            last = t
        since.append(None if last is None else t - last + 1)
    return since


def bucket(d):
    if d is None:
        return "before"
    return "1" if d == 1 else "2-8" if d <= 8 else "9-32" if d <= 32 else ">32"


def diagnose(model, tok, layers, row, schedules):
    prompt = tok(FEWSHOT + f"Q: {row['question']}\nA:", return_tensors="pt").input_ids[0].to(model.device)
    # generations start with a space after "A:", so the gold solution does too
    solution = tok(" " + row["solution"], add_special_tokens=False, return_tensors="pt").input_ids[0].to(model.device)
    steps = len(solution)
    full = {}
    for preset in ("large", "small"):
        select(layers, preset)
        full[preset] = model(input_ids=torch.cat([prompt, solution[:-1]])[None], use_cache=False,
                             logits_to_keep=steps).logits[0]
    gold_nll = {p: -full[p].float().log_softmax(-1).gather(-1, solution[:, None]).mean().item() for p in full}

    records = []
    for schedule in schedules:
        widths = [SCHEDULES[schedule](t) for t in range(steps)]
        chunks = run_lengths(widths)
        if len(chunks) == 1:
            continue  # the solution ends before this schedule's first switch
        mixed = run_chunks(model, layers, prompt, solution, chunks)
        fixed = {p: run_chunks(model, layers, prompt, solution, [[p, n] for _, n in chunks]) for p in full}
        is_large = torch.tensor([w == "large" for w in widths], device=model.device)[:, None]
        ref_fixed = torch.where(is_large, fixed["large"], fixed["small"])
        ref_full = torch.where(is_large, full["large"], full["small"])

        values = {}
        for ref, (a, b) in {"fixed": (mixed, ref_fixed), "full": (mixed, ref_full),
                            "drift": (ref_fixed, ref_full)}.items():
            js, top1, dnll = compare(a, b, solution)
            values |= {f"js_{ref}": js.tolist(), f"top1_{ref}": top1.float().tolist(), f"dnll_{ref}": dnll.tolist()}

        groups = {}
        for t, d in enumerate(steps_since_switch(widths)):
            groups.setdefault((widths[t], bucket(d)), []).append(t)
        for (width, b), idx in groups.items():
            record = {"id": row["id"], "schedule": schedule, "width": width, "bucket": b, "n_steps": len(idx)}
            records.append(record | {k: round(fmean(v[t] for t in idx), 6) for k, v in values.items()})
    return records, gold_nll


def summarize(records):
    """Average the per-example means, so every example counts equally."""
    groups = {}
    for r in records:
        groups.setdefault((r["schedule"], r["width"], r["bucket"]), []).append(r)
    table = []
    for schedule in MIXED:
        for width in ("large", "small"):
            for b in BUCKETS:
                rows = groups.get((schedule, width, b))
                if rows:
                    table.append({"schedule": schedule, "width": width, "bucket": b, "n_examples": len(rows),
                                  "n_steps": sum(r["n_steps"] for r in rows),
                                  **{k: round(fmean(r[k] for r in rows), 5) for k in METRICS}})
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--schedules", default=",".join(MIXED))
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()
    schedules = args.schedules.split(",")
    assert all(name in MIXED for name in schedules), schedules
    examples = [row for row in load_examples("dev") if row["diagnostic"]][:args.limit]

    run_id = new_run_id("diag-dev")
    out_dir = RESULTS / run_id
    manifest = run_manifest(run_id, SEED, "bfloat16", schedules=schedules, n_examples=len(examples))
    write_json(out_dir / "manifest.json", manifest)

    model, tok = load_model()
    layers = patch_widths(model)
    records, gold_nll = [], {"large": [], "small": []}
    with torch.inference_mode():
        for i, row in enumerate(examples):
            example_records, example_nll = diagnose(model, tok, layers, row, schedules)
            records += example_records
            for p in gold_nll:
                gold_nll[p].append(example_nll[p])
            print(f"example {i + 1}/{len(examples)}", flush=True)

    (out_dir / "diagnostics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in records))
    table = summarize(records)
    with (out_dir / "diagnostics_summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=table[0].keys())
        writer.writeheader()
        writer.writerows(table)
    manifest["full_prefix_gold_nll"] = {p: round(fmean(v), 4) for p, v in gold_nll.items()}
    write_json(out_dir / "manifest.json", manifest)

    print(f"gold NLL per step, full prefix: large {manifest['full_prefix_gold_nll']['large']:.4f}, "
          f"small {manifest['full_prefix_gold_nll']['small']:.4f}")
    for r in table:
        print(f"{r['schedule']:8} {r['width']:5} {r['bucket']:6} n={r['n_examples']:2}  "
              f"history: JS={r['js_fixed']:.4f} top1={r['top1_fixed']:.3f} dNLL={r['dnll_fixed']:+.4f}  "
              f"vs recompute: dNLL={r['dnll_full']:+.4f}  drift JS={r['js_drift']:.4f}")
    print(f"wrote {out_dir / 'diagnostics_summary.csv'} and diagnostics.jsonl")


if __name__ == "__main__":
    main()
