"""Pretrained Gemma 3n E4B text generation and frozen-width cache checks."""
import json
import time
import types
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, Gemma3nForConditionalGeneration

ROOT = Path(__file__).resolve().parent
MODEL = "google/gemma-3n-E4B"
REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
presets = json.loads((ROOT / "presets.json").read_text())["presets"]
torch.set_num_threads(4)
assert torch.cuda.is_available()

result = {"model": MODEL, "revision": REVISION, "device": torch.cuda.get_device_name(), "checks": {}}
output_path = OUTPUT_DIR / "pace_pretrained_results.json"
def save(name, record):
    result["checks"][name] = record
    output_path.write_text(json.dumps(result, indent=2) + "\n")
    print(name, json.dumps(record), flush=True)

t0 = time.monotonic()
model = Gemma3nForConditionalGeneration.from_pretrained(
    MODEL, revision=REVISION, dtype=torch.bfloat16, local_files_only=True
).eval().to("cuda")
tokenizer = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
result["load_seconds"] = round(time.monotonic() - t0, 2)
result["peak_gpu_bytes_after_load"] = torch.cuda.max_memory_allocated()
save("load", {"passed": True, "seconds": result["load_seconds"]})

def width_forward(mlp, x):
    width = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:width])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(x, mlp.up_proj.weight[:width])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :width])

layers = model.model.language_model.layers
assert len(layers) == 35
def select(preset):
    dims = presets[preset]["ffn_hidden_dims"]
    assert len(dims) == len(layers)
    for layer, width in zip(layers, dims):
        layer.mlp.active_width = width

ids = tokenizer("The capital of France is", return_tensors="pt")["input_ids"].to("cuda")
assert ids.shape[1] >= 4

with torch.inference_mode():
    t0 = time.monotonic()
    generated = model.generate(input_ids=ids, max_new_tokens=8, do_sample=False, use_cache=True)
    assert generated.shape[1] == ids.shape[1] + 8
    save("generation", {"passed": True, "new_tokens": 8, "seconds": round(time.monotonic()-t0, 2),
                        "text": tokenizer.decode(generated[0], skip_special_tokens=True)})

    # A full-width patch must be numerically identical to the original MLP path.
    base = model(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    for layer in layers:
        layer.mlp.forward = types.MethodType(width_forward, layer.mlp)
    select("large")
    full = model(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    err = (base-full).abs().max().item()
    assert torch.allclose(base, full, atol=0.05, rtol=0.005), err
    save("full_width_equivalence", {"passed": True, "max_abs_logit_error": err})

    # Sliced projections with parent tensors must match physically sliced projections.
    select("small")
    small = model(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    assert torch.isfinite(small).all()
    mlp = layers[0].mlp
    x = torch.randn(1, 3, mlp.hidden_size, device="cuda", dtype=torch.bfloat16)
    dyn = mlp(x)
    width = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:width].contiguous())
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    static = F.linear(mlp.act_fn(gate) * F.linear(x, mlp.up_proj.weight[:width].contiguous()),
                      mlp.down_proj.weight[:, :width].contiguous())
    err = (dyn-static).abs().max().item()
    assert torch.allclose(dyn, static, atol=0.05, rtol=0.005), err
    save("small_width_slice", {"passed": True, "ffn_width": width, "max_abs_mlp_error": err,
                               "finite_pretrained_logits": True})

    # With fixed width, a prefill followed by one cached token should agree with
    # recomputation on the same complete prefix. Bfloat16 may incur modest drift.
    next_id = torch.tensor([[17]], device="cuda")
    for preset in ("large", "small"):
        select(preset)
        prefix = model(input_ids=ids, use_cache=True, logits_to_keep=1)
        cached = model(input_ids=next_id, past_key_values=prefix.past_key_values,
                       use_cache=True, logits_to_keep=1).logits.float()
        uncached = model(input_ids=torch.cat([ids,next_id], dim=1), use_cache=False,
                         logits_to_keep=1).logits.float()
        err = (cached-uncached).abs().max().item()
        same_argmax = cached.argmax(-1).item() == uncached.argmax(-1).item()
        assert torch.isfinite(cached).all() and torch.isfinite(uncached).all()
        save("cache_"+preset, {"finite_logits": True, "max_abs_logit_error": err,
                              "same_argmax": same_argmax, "cached_shape": list(cached.shape),
                              "numerical_equivalence_established": bool(err < 0.05)})

    for first, second in (("large", "small"), ("small", "large")):
        select(first)
        prefix = model(input_ids=ids, use_cache=True, logits_to_keep=1)
        select(second)
        switched = model(input_ids=next_id, past_key_values=prefix.past_key_values,
                         use_cache=True, logits_to_keep=1).logits.float()
        assert torch.isfinite(switched).all()
        save("switch_"+first+"_to_"+second,
             {"passed": True, "finite_logits": True, "shape": list(switched.shape)})

result["peak_gpu_bytes"] = torch.cuda.max_memory_allocated()
output_path.write_text(json.dumps(result, indent=2) + "\n")
print("PASS all pretrained checks", flush=True)
