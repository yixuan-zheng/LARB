"""Compare dynamic Small with a separate static Small text model built from the E4B tensors."""
import copy
import json
import types
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, Gemma3nForCausalLM, Gemma3nForConditionalGeneration

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
MODEL = "google/gemma-3n-E4B"
REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
widths = json.loads((ROOT / "presets.json").read_text())["presets"]["small"]["ffn_hidden_dims"]
torch.set_num_threads(4)
parent = Gemma3nForConditionalGeneration.from_pretrained(
    MODEL, revision=REVISION, dtype=torch.bfloat16, local_files_only=True
).eval().to("cuda")
tok = AutoTokenizer.from_pretrained(MODEL, revision=REVISION, local_files_only=True)
ids = tok("The capital of France is", return_tensors="pt")["input_ids"].to("cuda")

def width_forward(mlp, x):
    width = mlp.active_width
    gate = F.linear(x, mlp.gate_proj.weight[:width])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(x, mlp.up_proj.weight[:width])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :width])

for layer, width in zip(parent.model.language_model.layers, widths):
    layer.mlp.active_width = width
    layer.mlp.forward = types.MethodType(width_forward, layer.mlp)

config = copy.deepcopy(parent.config.text_config)
config.intermediate_size = widths
with torch.device("meta"):
    static = Gemma3nForCausalLM(config).eval()

source = parent.state_dict()
mapped = {}
for name, target in static.state_dict().items():
    source_name = ("model.language_model." + name[len("model."):]) if name.startswith("model.") else name
    tensor = source[source_name]
    if ".mlp.gate_proj.weight" in name or ".mlp.up_proj.weight" in name:
        layer_id = int(name.split("layers.")[1].split(".")[0])
        tensor = tensor[:widths[layer_id]]
    elif ".mlp.down_proj.weight" in name:
        layer_id = int(name.split("layers.")[1].split(".")[0])
        tensor = tensor[:, :widths[layer_id]]
    assert tensor.shape == target.shape, (name, tensor.shape, target.shape)
    mapped[name] = tensor
static.load_state_dict(mapped, strict=True, assign=True)
# Nonpersistent buffers are absent from state_dict (notably embed_scale).
source_buffers = dict(parent.named_buffers())
for name, buffer in list(static.named_buffers()):
    if buffer.device.type == "meta":
        source_name = ("model.language_model." + name[len("model."):]) if name.startswith("model.") else name
        assert source_name in source_buffers, (name, source_name)
        module_name, attribute = name.rsplit(".", 1)
        setattr(static.get_submodule(module_name), attribute, source_buffers[source_name])
assert not any(parameter.device.type == "meta" for parameter in static.parameters())
assert not any(buffer.device.type == "meta" for buffer in static.buffers())
static.eval()
with torch.inference_mode():
    dynamic_logits = parent(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    static_logits = static(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    err = (dynamic_logits-static_logits).abs().max().item()
    same_argmax = dynamic_logits.argmax(-1).item() == static_logits.argmax(-1).item()
    assert torch.allclose(dynamic_logits, static_logits, atol=0.05, rtol=0.005), err

result = {"model": MODEL, "revision": REVISION, "preset": "small", "dtype": "bfloat16",
          "static_model": "separate Gemma3nForCausalLM with physically sliced E4B tensor views",
          "layers": len(widths), "sliced_layers": sum(width < 16384 for width in widths),
          "max_abs_logit_error": err, "same_argmax": same_argmax, "passed": True}
(OUTPUT_DIR / "pace_static_small.json").write_text(json.dumps(result, indent=2)+"\n")
print(json.dumps(result, indent=2), flush=True)
