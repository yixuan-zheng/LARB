"""Bounded multi-prompt E4B cache, retained-history, and timing pilot.

Teacher-forced text only; one request at a time. This is not a quality or
continuous-batching benchmark.
"""
import json
import statistics
import time
import types
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, Gemma3nForConditionalGeneration

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL = "google/gemma-3n-E4B"
REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
PROMPTS = [
    ("The capital of France is", " Paris, a major European city."),
    ("In Python, a list comprehension is used to", " create a new list."),
    ("To make a cup of tea, first", " heat the water."),
    ("Photosynthesis converts sunlight into", " chemical energy in plants."),
]
presets = json.loads((ROOT / "presets.json").read_text())["presets"]
torch.set_num_threads(4)
assert torch.cuda.is_available()
model = Gemma3nForConditionalGeneration.from_pretrained(
    MODEL, revision=REVISION, dtype=torch.bfloat16, local_files_only=True
).eval().to("cuda")
tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
cases = []
for prompt, continuation in PROMPTS:
    ids = tok(prompt, return_tensors="pt")["input_ids"].to("cuda")
    continuation_ids = tok(continuation, add_special_tokens=False, return_tensors="pt")["input_ids"].to("cuda")
    assert continuation_ids.shape[1] >= 3
    cases.append((prompt, continuation, ids, continuation_ids))

def metrics(a, b):
    a, b = a.float().flatten(), b.float().flatten()
    diff = (a-b).abs()
    p, q = torch.softmax(a, dim=0), torch.softmax(b, dim=0)
    m = (p+q)/2
    js = (0.5 * torch.where(p > 0, p * (p.clamp_min(1e-30)/m.clamp_min(1e-30)).log(), 0).sum()
          + 0.5 * torch.where(q > 0, q * (q.clamp_min(1e-30)/m.clamp_min(1e-30)).log(), 0).sum())
    top_a = torch.topk(a, 5).indices.tolist()
    top_b = torch.topk(b, 5).indices.tolist()
    return {"top1_agrees": bool(top_a[0] == top_b[0]),
            "top5_overlap": len(set(top_a) & set(top_b)),
            "mean_abs_logit": diff.mean().item(), "max_abs_logit": diff.max().item(),
            "total_variation": (0.5*(p-q).abs().sum()).item(),
            "jensen_shannon_nats": js.item()}

def forward(ids, cache=None):
    return model(input_ids=ids, past_key_values=cache, use_cache=True, logits_to_keep=1)

def width_forward(mlp, x):
    width = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:width])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(x, mlp.up_proj.weight[:width])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :width])

layers = model.model.language_model.layers
def select(preset):
    for layer, width in zip(layers, presets[preset]["ffn_hidden_dims"]):
        layer.mlp.active_width = width

record = {"model": MODEL, "revision": REVISION, "dtype": "bfloat16", "device": torch.cuda.get_device_name(),
          "design": "four prompts, teacher-forced continuations, one request, no batching",
          "fixed_width": [], "switches": [], "timing": []}
OUT = OUTPUT_DIR / "pace_bounded_research.json"
def save():
    OUT.write_text(json.dumps(record, indent=2)+"\n")

with torch.inference_mode():
    # Unmodified stock model first; retain its logits to check the patched
    # Large path itself, not merely its cache-vs-recompute discrepancy.
    stock = {}
    for i, (prompt, continuation, ids, continuation_ids) in enumerate(cases):
        token = continuation_ids[:, :1]
        prefill = forward(ids)
        cached = forward(token, prefill.past_key_values).logits.float().clone()
        full = model(input_ids=torch.cat([ids, token], 1), use_cache=False,
                     logits_to_keep=1).logits.float().clone()
        stock[i] = (cached, full)
        record["fixed_width"].append({"prompt_id": i, "mode": "stock_large",
                                       "prefix_tokens": ids.shape[1], "comparison": metrics(cached, full)})
        save()

    for layer in layers:
        layer.mlp.forward = types.MethodType(width_forward, layer.mlp)

    for i, (prompt, continuation, ids, continuation_ids) in enumerate(cases):
        token = continuation_ids[:, :1]
        for preset in ("large", "small"):
            select(preset)
            prefill = forward(ids)
            cached = forward(token, prefill.past_key_values).logits.float().clone()
            full = model(input_ids=torch.cat([ids, token], 1), use_cache=False,
                         logits_to_keep=1).logits.float().clone()
            item = {"prompt_id": i, "mode": "patched_"+preset,
                    "prefix_tokens": ids.shape[1], "comparison": metrics(cached, full)}
            if preset == "large":
                item["vs_stock_cached"] = metrics(cached, stock[i][0])
                item["vs_stock_full"] = metrics(full, stock[i][1])
            record["fixed_width"].append(item)
            save()

    # Each final-width fixed-cache baseline processes exactly the same prefix
    # and teacher-forced continuation. A mixed-history cache is not expected
    # to equal a recomputation that changes the width of prior tokens.
    schedules = {
        "large_to_small": ["large", "small", "small", "small"],
        "small_to_large": ["small", "large", "large", "large"],
        "alternating": ["large", "small", "large", "small"],
    }
    for i, (prompt, continuation, ids, continuation_ids) in enumerate(cases):
        tokens = [continuation_ids[:, j:j+1] for j in range(3)]
        fixed = {}
        for preset in ("large", "small"):
            select(preset)
            state = forward(ids)
            for token in tokens:
                state = forward(token, state.past_key_values)
            fixed[preset] = state.logits.float().clone()
        for name, schedule in schedules.items():
            select(schedule[0])
            state = forward(ids)
            for token, preset in zip(tokens, schedule[1:]):
                select(preset)
                state = forward(token, state.past_key_values)
            final_width = schedule[-1]
            mixed = state.logits.float().clone()
            select(final_width)
            recompute = model(input_ids=torch.cat([ids]+tokens, 1), use_cache=False,
                              logits_to_keep=1).logits.float().clone()
            record["switches"].append({"prompt_id": i, "schedule": name,
               "width_history": schedule, "final_width": final_width,
               "vs_fixed_final_width_cache": metrics(mixed, fixed[final_width]),
               "vs_full_prefix_final_width": metrics(mixed, recompute),
               "fixed_cache_vs_full_prefix": metrics(fixed[final_width], recompute)})
            save()

    # Timing is deliberately single-request eager PyTorch, with GPU
    # synchronization, three repeats, and no serving-runtime claims.
    for i, (prompt, continuation, ids, continuation_ids) in enumerate(cases):
        token = continuation_ids[:, :1]
        for mode in ("patched_large", "patched_small"):
            select(mode.split("_")[1])
            # Warm both prefill and decode kernels.
            warm = forward(ids)
            forward(token, warm.past_key_values)
            prefill_ms, decode_ms = [], []
            for _ in range(3):
                torch.cuda.synchronize()
                t0 = time.perf_counter()
                state = forward(ids)
                torch.cuda.synchronize()
                prefill_ms.append(1000*(time.perf_counter()-t0))
                t0 = time.perf_counter()
                forward(token, state.past_key_values)
                torch.cuda.synchronize()
                decode_ms.append(1000*(time.perf_counter()-t0))
            record["timing"].append({"prompt_id": i, "mode": mode,
               "prefill_ms": prefill_ms, "decode_ms": decode_ms,
               "prefill_median_ms": statistics.median(prefill_ms),
               "decode_median_ms": statistics.median(decode_ms)})
            save()

record["completed"] = True
save()
print("PASS bounded research pilot", flush=True)
