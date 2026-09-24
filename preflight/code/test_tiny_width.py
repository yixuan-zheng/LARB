"""Compare a switchable Gemma 3n FFN with the stock and sliced implementations.

Random small weights; no pretrained model is downloaded. This tests computation
only, not pretrained quality or performance.
"""
import copy
import json
import types
from pathlib import Path

import torch
import torch.nn.functional as F
from transformers import Gemma3nForCausalLM, Gemma3nTextConfig

ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT.parent / "run-output"
OUTPUT_DIR.mkdir(exist_ok=True)
torch.manual_seed(6222)
torch.set_num_threads(4)
base = Gemma3nTextConfig(
    vocab_size=256, vocab_size_per_layer_input=256,
    hidden_size=64, hidden_size_per_layer_input=8,
    num_hidden_layers=10, num_attention_heads=4, num_key_value_heads=2,
    head_dim=16, intermediate_size=[64] * 10,
    num_kv_shared_layers=5, laurel_rank=8,
    max_position_embeddings=128, sliding_window=64,
    activation_sparsity_pattern=[0.95] * 2 + [0.0] * 8,
)
parent = Gemma3nForCausalLM(base).eval()
input_ids = torch.tensor([[2, 17, 31, 44, 53, 69]], dtype=torch.long)


def logits(model):
    return model(input_ids=input_ids, use_cache=False, return_dict=True).logits.float()


def sliced_forward(mlp, hidden_states):
    width = mlp.active_width
    gate = F.linear(hidden_states, mlp.gate_proj.weight[:width])
    if mlp.activation_sparsity > 0:
        gate = mlp._gaussian_topk(gate)
    up = F.linear(hidden_states, mlp.up_proj.weight[:width])
    return F.linear(mlp.act_fn(gate) * up, mlp.down_proj.weight[:, :width])


def select_width(model, width):
    for layer in model.model.layers:
        layer.mlp.active_width = width


with torch.inference_mode():
    reference_full = logits(parent)
    for layer in parent.model.layers:
        layer.mlp.active_width = 64
        layer.mlp.forward = types.MethodType(sliced_forward, layer.mlp)
    dynamic_full = logits(parent)
    full_error = (dynamic_full - reference_full).abs().max().item()
    assert torch.allclose(dynamic_full, reference_full, atol=1e-5, rtol=1e-5), full_error

    select_width(parent, 32)
    dynamic_small = logits(parent)
    small_config = copy.deepcopy(base)
    small_config.intermediate_size = [32] * 10
    extracted = Gemma3nForCausalLM(small_config).eval()
    parent_state = parent.state_dict()
    sliced_state = {}
    for key, target in extracted.state_dict().items():
        tensor = parent_state[key]
        if ".mlp.gate_proj.weight" in key or ".mlp.up_proj.weight" in key:
            tensor = tensor[:32]
        elif ".mlp.down_proj.weight" in key:
            tensor = tensor[:, :32]
        assert tensor.shape == target.shape, (key, tensor.shape, target.shape)
        sliced_state[key] = tensor
    extracted.load_state_dict(sliced_state, strict=True)
    static_small = logits(extracted)
    small_error = (dynamic_small - static_small).abs().max().item()
    assert torch.allclose(dynamic_small, static_small, atol=1e-5, rtol=1e-5), small_error
    select_width(parent, 64)
    restored_error = (logits(parent) - reference_full).abs().max().item()
    assert restored_error < 1e-5

record = {
    "torch": torch.__version__,
    "model": "Gemma3nForCausalLM, randomly initialized tiny 10-layer model",
    "widths": [32, 64],
    "activation_sparsity_tested": True,
    "full_vs_stock_max_abs_logit_error": full_error,
    "narrow_vs_extracted_max_abs_logit_error": small_error,
    "restored_full_max_abs_logit_error": restored_error,
    "tolerance_atol_rtol": 1e-5,
    "passed": True,
}
(OUTPUT_DIR / "tiny_width_results.json").write_text(json.dumps(record, indent=2) + "\n")
print(json.dumps(record, indent=2))
