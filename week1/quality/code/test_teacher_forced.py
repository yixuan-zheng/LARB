"""CPU check of the chunked teacher-forced forward on a tiny random 35-layer Gemma 3n (no download)."""
import torch
from transformers import Gemma3nForCausalLM, Gemma3nTextConfig

import common
from schedules import SCHEDULES, run_lengths
from teacher_forced import compare, run_chunks, steps_since_switch

torch.manual_seed(6222)
config = Gemma3nTextConfig(
    vocab_size=256, vocab_size_per_layer_input=256, hidden_size=64, hidden_size_per_layer_input=8,
    num_hidden_layers=35, num_attention_heads=4, num_key_value_heads=2, head_dim=16,
    intermediate_size=[64] * 35, num_kv_shared_layers=15, laurel_rank=8,
    max_position_embeddings=256, sliding_window=64,
    activation_sparsity_pattern=[0.95] * 10 + [0.0] * 25, pad_token_id=0, eos_token_id=1,
)
model = Gemma3nForCausalLM(config).eval()
for preset in common.PRESETS.values():
    preset["ffn_hidden_dims"] = [d // 256 for d in preset["ffn_hidden_dims"]]
layers = common.patch_widths(model)

# prompt + solution is longer than the sliding window, so chunks cross it
prompt, solution = torch.randint(2, 256, (40,)), torch.randint(2, 256, (90,))
steps = len(solution)


def widths(name):
    return [SCHEDULES[name](t) for t in range(steps)]


with torch.inference_mode():
    for preset in ("large", "small"):
        common.select(layers, preset)
        full = model(input_ids=torch.cat([prompt, solution[:-1]])[None], use_cache=False,
                     logits_to_keep=steps).logits[0]
        for name in ("static_L", "LS_early", "LS_late", "alt4"):
            chunks = [[preset, n] for _, n in run_lengths(widths(name))]
            # at one width, cached chunks must reproduce the uncached forward
            assert torch.allclose(run_chunks(model, layers, prompt, solution, chunks), full, atol=1e-4), (preset, name)

    for name in ("LS_late", "SL_early", "alt16"):
        chunks = run_lengths(widths(name))
        mixed = run_chunks(model, layers, prompt, solution, chunks)
        fixed = run_chunks(model, layers, prompt, solution, [[chunks[0][0], n] for _, n in chunks])
        before = chunks[0][1]
        # before the first switch the history is identical, so the logits must be too
        assert torch.equal(mixed[:before], fixed[:before]), name
        assert not torch.allclose(mixed[before:], fixed[before:]), name

    js, top1, dnll = compare(full, full, solution)
    assert js.abs().max() < 1e-6 and top1.all() and (dnll == 0).all()

assert steps_since_switch(["large", "large", "small", "small", "large"]) == [None, None, 1, 2, 1]
print("PASS: chunked forward matches the uncached forward; history is shared until the first switch")
