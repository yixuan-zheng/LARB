"""Four-prompt float32 cache-vs-recompute control for patched Small/Large."""
import json
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
presets = json.loads((ROOT / "presets.json").read_text())["presets"]
prompts = [
    ("The capital of France is", " Paris, a major European city."),
    ("In Python, a list comprehension is used to", " create a new list."),
    ("To make a cup of tea, first", " heat the water."),
    ("Photosynthesis converts sunlight into", " chemical energy in plants."),
]
torch.set_num_threads(4)
model = Gemma3nForConditionalGeneration.from_pretrained(
    MODEL, revision=REVISION, dtype=torch.float32, local_files_only=True
).eval().to("cuda")
tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)

def width_forward(mlp, x):
    w = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:w])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    return F.linear(mlp.act_fn(gate) * F.linear(x, mlp.up_proj.weight[:w]),
                    mlp.down_proj.weight[:, :w])

layers = model.model.language_model.layers
for layer in layers:
    layer.mlp.forward = types.MethodType(width_forward, layer.mlp)

results = []
with torch.inference_mode():
    for i, (prompt, continuation) in enumerate(prompts):
        ids = tok(prompt, return_tensors="pt")["input_ids"].to("cuda")
        token = tok(continuation, add_special_tokens=False, return_tensors="pt")["input_ids"][:, :1].to("cuda")
        for preset in ("large", "small"):
            for layer, width in zip(layers, presets[preset]["ffn_hidden_dims"]):
                layer.mlp.active_width = width
            prefill = model(input_ids=ids, use_cache=True, logits_to_keep=1)
            cached = model(input_ids=token, past_key_values=prefill.past_key_values,
                           use_cache=True, logits_to_keep=1).logits.float().flatten()
            full = model(input_ids=torch.cat([ids, token], dim=1), use_cache=False,
                         logits_to_keep=1).logits.float().flatten()
            diff = (cached-full).abs()
            p, q = torch.softmax(cached, 0), torch.softmax(full, 0)
            results.append({"prompt_id": i, "preset": preset,
                            "mean_abs_logit": diff.mean().item(),
                            "max_abs_logit": diff.max().item(),
                            "total_variation": (0.5*(p-q).abs().sum()).item(),
                            "top1_agrees": bool(cached.argmax() == full.argmax())})
            print(results[-1], flush=True)
out = {"model": MODEL, "revision": REVISION, "dtype": "float32", "results": results}
(OUTPUT_DIR / "pace_precision_small.json").write_text(json.dumps(out, indent=2)+"\n")
