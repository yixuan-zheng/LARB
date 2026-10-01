"""CPU check of the schedule hook on a tiny random 35-layer Gemma 3n (no download).

Records the width each forward pass actually used and compares it with the
schedule, for a single prompt and a left-padded batch.
"""
import torch
from transformers import Gemma3nForCausalLM, Gemma3nTextConfig

import common
from schedules import SCHEDULES, WidthScheduleProcessor, run_lengths

STEPS = 80
torch.manual_seed(6222)
config = Gemma3nTextConfig(
    vocab_size=256, vocab_size_per_layer_input=256, hidden_size=64, hidden_size_per_layer_input=8,
    num_hidden_layers=35, num_attention_heads=4, num_key_value_heads=2, head_dim=16,
    intermediate_size=[64] * 35, num_kv_shared_layers=15, laurel_rank=8,
    max_position_embeddings=256, sliding_window=64,
    activation_sparsity_pattern=[0.95] * 10 + [0.0] * 25, pad_token_id=0, eos_token_id=1,
)
model = Gemma3nForCausalLM(config).eval()

# scale the real presets to the tiny model: 16384 -> 64, 8192 -> 32
for preset in common.PRESETS.values():
    preset["ffn_hidden_dims"] = [d // 256 for d in preset["ffn_hidden_dims"]]


def generate(input_ids, attention_mask, processor=None):
    return model.generate(input_ids=input_ids, attention_mask=attention_mask, max_new_tokens=STEPS,
                          min_new_tokens=STEPS, do_sample=False,
                          logits_processor=[processor] if processor else None)


single = torch.tensor([[2, 17, 31, 44, 53, 69]])
batch = torch.tensor([[0, 0, 2, 17, 31, 44], [2, 9, 8, 7, 6, 5]])  # left-padded
inputs = [(single, torch.ones_like(single)), (batch, (batch != 0).long())]

with torch.inference_mode():
    stock = [generate(*x) for x in inputs]
    layers = common.patch_widths(model)

    # layer 0 is narrow in Small and full in Large, so its width identifies the preset used
    used = []
    layers[0].mlp.register_forward_pre_hook(lambda mlp, args: used.append(mlp.active_width))
    width_of = {name: p["ffn_hidden_dims"][0] for name, p in common.PRESETS.items()}

    for name, schedule in SCHEDULES.items():
        for (ids, mask), reference in zip(inputs, stock):
            used.clear()
            processor = WidthScheduleProcessor(layers, name, ids.shape[1])
            out = generate(ids, mask, processor)
            expected = [schedule(step) for step in range(STEPS)]
            assert used == [width_of[p] for p in expected], name
            assert processor.history[:STEPS] == expected, name
            if name == "static_L":
                assert torch.equal(out, reference), "static_L != stock"
        print(f"{name:9} ok  {run_lengths(expected)}")
print("PASS: every forward pass used the scheduled width; static_L matches the unpatched model")
