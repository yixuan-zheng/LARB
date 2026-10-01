"""Greedy GSM8K generation under width schedules; one JSONL row per (schedule, example).

Batches are built once (sorted by prompt length) and are identical for every
schedule, so paired comparisons see the same padding. Re-running with the same
--run-id skips finished batches (e.g. after a PACE time limit) and can add new
schedules to the same run.

  python run_generation.py --split dev --limit 16                      # smoke test
  python run_generation.py --split dev --run-id <id> --schedules LS_late,SL_late
"""
import argparse
import json
import time

import torch

from common import MANIFESTS, RESULTS, load_model, new_run_id, patch_widths, run_manifest, write_json
from schedules import SCHEDULES, WidthScheduleProcessor, run_lengths

SEED = 6222
DECODING = json.loads((MANIFESTS / "quality_contract.json").read_text())["decoding"]
FEWSHOT = (MANIFESTS / "fewshot_prompt.txt").read_text()


def load_examples(split, limit=None):
    rows = [json.loads(line) for line in (MANIFESTS / "gsm8k_eval.jsonl").open()]
    return [row for row in rows if row["split"] == split][:limit]


def make_batches(tok, rows, batch_size):
    prompts = {row["id"]: FEWSHOT + f"Q: {row['question']}\nA:" for row in rows}
    # similar lengths per batch means less padding and less wasted compute
    rows = sorted(rows, key=lambda row: (len(tok(prompts[row["id"]]).input_ids), row["id"]))
    rows = [(row, prompts[row["id"]]) for row in rows]
    return [rows[i:i + batch_size] for i in range(0, len(rows), batch_size)]


def generate_batch(model, tok, layers, batch, schedule):
    enc = tok([prompt for _, prompt in batch], return_tensors="pt", padding=True).to(model.device)
    prompt_len = enc.input_ids.shape[1]
    processor = WidthScheduleProcessor(layers, schedule, prompt_len)
    start = time.perf_counter()
    out = model.generate(**enc, do_sample=False, max_new_tokens=DECODING["max_new_tokens"],
                         stop_strings=DECODING["stop_strings"], tokenizer=tok,
                         logits_processor=[processor])
    seconds = time.perf_counter() - start

    records = []
    for i, (row, _) in enumerate(batch):
        generated = out[i, prompt_len:].tolist()
        # rows that finish early are padded until the whole batch stops
        n = generated.index(tok.pad_token_id) if tok.pad_token_id in generated else len(generated)
        text = tok.decode(generated[:n], skip_special_tokens=True)
        history = processor.history[:n]
        runs = run_lengths(history)
        if any(stop in text for stop in DECODING["stop_strings"]):
            stop_reason = "stop_string"
        else:
            stop_reason = "eos" if n < DECODING["max_new_tokens"] else "length"
        records.append({
            "schedule": schedule, "id": row["id"], "split": row["split"],
            "prompt_len": int(enc.attention_mask[i].sum()), "generated_len": n,
            "width_history": runs, "n_switches": len(runs) - 1,
            "frac_small": history.count("small") / n,
            "text": text, "stop_reason": stop_reason, "batch_seconds": round(seconds, 3),
        })
    return records


def run(model, tok, layers, batches, schedules, out_dir, run_id):
    path = out_dir / "generations.jsonl"
    done = set()
    if path.exists():
        done = {(r["schedule"], r["id"]) for r in map(json.loads, path.open())}
    with path.open("a") as f:
        for schedule in schedules:
            for b, batch in enumerate(batches):
                # rerun whole batches only, so batch composition never changes on resume
                if all((schedule, row["id"]) in done for row, _ in batch):
                    continue
                records = generate_batch(model, tok, layers, batch, schedule)
                for record in records:
                    if (schedule, record["id"]) not in done:
                        f.write(json.dumps({"run_id": run_id, "batch": b, **record}) + "\n")
                f.flush()
                print(f"{schedule} batch {b + 1}/{len(batches)} {records[0]['batch_seconds']:.1f}s", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", required=True, choices=["dev", "heldout"])
    parser.add_argument("--schedules", default="static_L,static_S,LS_early,SL_early")
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    schedules = args.schedules.split(",")
    assert all(name in SCHEDULES for name in schedules), schedules

    run_id = args.run_id or new_run_id(f"gen-{args.split}")
    out_dir = RESULTS / run_id
    manifest_path = out_dir / "manifest.json"
    settings = {"split": args.split, "batch_size": args.batch_size, "limit": args.limit}
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        # same examples and batches are required for paired comparisons within a run
        assert all(manifest[k] == v for k, v in settings.items()), "resume must use the same split/batch size/limit"
        for name in schedules:
            if name not in manifest["schedules"]:
                manifest["schedules"].append(name)
    else:
        manifest = run_manifest(run_id, SEED, "bfloat16", **settings, schedules=schedules, decoding=DECODING)
    write_json(manifest_path, manifest)

    model, tok = load_model()
    tok.padding_side = "left"
    layers = patch_widths(model)
    batches = make_batches(tok, load_examples(args.split, args.limit), args.batch_size)
    with torch.inference_mode():
        run(model, tok, layers, batches, schedules, out_dir, run_id)
    print(f"done: {out_dir / 'generations.jsonl'}")


if __name__ == "__main__":
    main()
