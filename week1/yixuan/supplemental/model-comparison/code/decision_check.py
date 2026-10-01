"""Small decision screen: curated cloze likelihood and synchronized eager timing.
No external dataset, training, serving engine, or final quality claim.
Run with --model nanochat|gemma --output results.json. Checkpoints must be cached.
"""

import argparse, json, time, statistics, types
from pathlib import Path
import torch
import torch.nn.functional as F

p = argparse.ArgumentParser()
p.add_argument("--model", choices=["nanochat", "gemma"], required=True)
p.add_argument("--output", required=True)
a = p.parse_args()
torch.set_num_threads(4)
torch.manual_seed(7)
# Explicit curated diagnostic; three choices, correct answer first before scoring.
CASES = [
    ("The capital of France is", " Paris", " Rome", " Berlin"),
    ("The capital of Japan is", " Tokyo", " Madrid", " London"),
    ("The capital of Italy is", " Rome", " Paris", " Tokyo"),
    ("The capital of Germany is", " Berlin", " Rome", " Madrid"),
    ("The capital of Spain is", " Madrid", " Tokyo", " Berlin"),
    ("The largest planet in our solar system is", " Jupiter", " Mars", " Venus"),
    ("The planet closest to the Sun is", " Mercury", " Saturn", " Neptune"),
    ("Water freezes at zero degrees", " Celsius", " Fahrenheit", " Kelvin"),
    ("The chemical symbol for oxygen is", " O", " H", " C"),
    ("The chemical symbol for gold is", " Au", " Ag", " Fe"),
    ("A triangle has", " three sides", " four sides", " five sides"),
    ("A week has", " seven days", " six days", " eight days"),
    ("An hour contains", " sixty minutes", " thirty minutes", " ninety minutes"),
    ("The opposite of hot is", " cold", " warm", " bright"),
    ("The opposite of north is", " south", " east", " west"),
    ("Birds are covered in", " feathers", " scales", " fur"),
    ("Fish breathe through", " gills", " lungs", " wings"),
    ("Plants use sunlight for", " photosynthesis", " digestion", " evaporation"),
    ("The organ that pumps blood is the", " heart", " liver", " stomach"),
    ("The Earth orbits the", " Sun", " Moon", " Mars"),
    ("In Python, a function is declared using", " def", " class", " import"),
    ("In Python, the boolean values are True and", " False", " None", " zero"),
    ("The language used to style HTML pages is", " CSS", " SQL", " CSV"),
    ("A kilogram contains one thousand", " grams", " meters", " liters"),
]
record = {
    "model": a.model,
    "gpu": torch.cuda.get_device_name(),
    "torch": torch.__version__,
    "dtype": "bfloat16",
    "quality_design": "24 hand-written 3-choice cloze examples; mean continuation log probability; diagnostic only",
    "quality": [],
    "timing": [],
    "switches": [],
}
out = Path(a.output)
out.parent.mkdir(parents=True, exist_ok=True)


def save():
    out.write_text(json.dumps(record, indent=2) + "\n")


if a.model == "nanochat":
    from matformer import load_checkpoint
    import os

    model, tok, _ = load_checkpoint(
        device="cuda", dtype=torch.bfloat16, cache_dir=os.environ["HF_HOME"]
    )
    modes = ["XL", "L", "M", "S"]
    active = "XL"

    def encode(s, bos=True):
        return (
            [tok.encode_single_token("<|bos|>")] if bos else []
        ) + tok.encode_ordinary(s)

    def select(mode):
        global active
        active = mode

    def run(ids, cache=None):
        return model(ids, kv_cache=cache, ffn_hidden_dim=active), cache

    def newcache(batch, length):
        return model.new_cache(batch_size=batch, max_seq_len=length)

    def physical_small():
        for block in model.transformer.h:
            mlp = block.mlp
            mlp.c_fc.weight = torch.nn.Parameter(mlp.c_fc.weight[:640].contiguous())
            mlp.c_proj.weight = torch.nn.Parameter(
                mlp.c_proj.weight[:, :640].contiguous()
            )

else:
    from transformers import AutoTokenizer, Gemma3nForConditionalGeneration

    revision = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
    model = (
        Gemma3nForConditionalGeneration.from_pretrained(
            "google/gemma-3n-E4B",
            revision=revision,
            dtype=torch.bfloat16,
            local_files_only=True,
        )
        .eval()
        .to("cuda")
    )
    tok = AutoTokenizer.from_pretrained(
        "google/gemma-3n-E4B", revision=revision, local_files_only=True
    )
    presets = json.loads(Path(__file__).with_name("presets.json").read_text())[
        "presets"
    ]
    modes = ["large", "medium", "small"]
    layers = model.model.language_model.layers

    def width_forward(mlp, x):
        w = mlp.active_width
        gate = F.linear(x, mlp.gate_proj.weight[:w])
        if mlp.activation_sparsity > 0:
            gate = mlp._gaussian_topk(gate)
        return F.linear(
            mlp.act_fn(gate) * F.linear(x, mlp.up_proj.weight[:w]),
            mlp.down_proj.weight[:, :w],
        )

    for layer in layers:
        layer.mlp.forward = types.MethodType(width_forward, layer.mlp)

    def encode(s, bos=True):
        return tok.encode(s, add_special_tokens=bos)

    def select(mode):
        for layer, w in zip(layers, presets[mode]["ffn_hidden_dims"]):
            layer.mlp.active_width = w

    def run(ids, cache=None):
        r = model(
            input_ids=ids,
            past_key_values=cache,
            use_cache=True,
            logits_to_keep=1 if last_only else 0,
        )
        return r.logits, r.past_key_values

    def newcache(batch, length):
        return None

    def physical_small():
        for layer, w in zip(layers, presets["small"]["ffn_hidden_dims"]):
            m = layer.mlp
            for name in ["gate_proj", "up_proj"]:
                getattr(m, name).weight = torch.nn.Parameter(
                    getattr(m, name).weight[:w].contiguous()
                )
            m.down_proj.weight = torch.nn.Parameter(
                m.down_proj.weight[:, :w].contiguous()
            )


last_only = False
large, small = modes[0], modes[-1]
with torch.inference_mode():
    for mode in modes:
        select(mode)
        for i, (prompt, *options) in enumerate(CASES):
            prefix = encode(prompt)
            scores = []
            for text in options:
                continuation = encode(text, False)
                ids = torch.tensor([prefix + continuation], device="cuda")
                logits, _ = run(ids)
                positions = (
                    logits[0, len(prefix) - 1 : len(prefix) + len(continuation) - 1]
                    .float()
                    .log_softmax(-1)
                )
                score = (
                    positions.gather(
                        1, torch.tensor(continuation, device="cuda")[:, None]
                    )
                    .mean()
                    .item()
                )
                scores.append(score)
            record["quality"].append(
                {
                    "id": i,
                    "mode": mode,
                    "prompt": prompt,
                    "options": options,
                    "scores_mean_logprob": scores,
                    "correct": scores.index(max(scores)) == 0,
                    "margin": scores[0] - max(scores[1:]),
                }
            )
        save()
        print(
            "quality",
            mode,
            sum(x["correct"] for x in record["quality"] if x["mode"] == mode),
            flush=True,
        )
    last_only = True
    # Forced fixed suffix avoids generation divergence confounding timing and history diagnostics.
    base = encode("A scientist studies the natural world. " * 100)

    def timing(mode, batch, length, label):
        select(mode)
        ids = torch.tensor([base[:length]] * batch, device="cuda")
        token = ids[:, -1:]
        trials = []
        for repeat in range(4):
            cache = newcache(batch, length + 16)
            torch.cuda.synchronize()
            t = time.perf_counter()
            _, cache = run(ids, cache)
            torch.cuda.synchronize()
            pre = (time.perf_counter() - t) * 1000
            torch.cuda.synchronize()
            t = time.perf_counter()
            for _ in range(16):
                _, cache = run(token, cache)
            torch.cuda.synchronize()
            decode = (time.perf_counter() - t) * 1000 / 16
            if repeat:
                trials.append({"prefill_ms": pre, "decode_ms": decode})
        row = {
            "mode": label,
            "batch": batch,
            "context": length,
            "prefill_ms": statistics.median(x["prefill_ms"] for x in trials),
            "decode_ms": statistics.median(x["decode_ms"] for x in trials),
            "trials": trials,
        }
        record["timing"].append(row)
        save()
        print(
            "timing", row["mode"], batch, length, round(row["decode_ms"], 3), flush=True
        )

    for batch in [1, 8]:
        for length in [32, 256]:
            for mode in [large, small]:
                timing(mode, batch, length, mode)
    for source, target in [(large, small), (small, large)]:
        ids = torch.tensor([base[:32]], device="cuda")
        select(source)
        _, cache = run(ids, newcache(1, 48))
        steps = []
        for step in range(8):
            select(target if step < 4 else source)
            torch.cuda.synchronize()
            t = time.perf_counter()
            logits, cache = run(ids[:, -1:], cache)
            torch.cuda.synchronize()
            steps.append((time.perf_counter() - t) * 1000)
            assert torch.isfinite(logits).all()
        record["switches"].append(
            {"schedule": [source, target, source], "step_ms": steps, "finite": True}
        )
        save()
    # Same forward implementation with compact contiguous Small weights: isolates layout/storage, not an optimized serving engine.
    select(small)
    ids = torch.tensor([base[:32]], device="cuda")
    before, _ = run(ids, newcache(1, 48))
    before = before.float().clone()
    physical_small()
    after, _ = run(ids, newcache(1, 48))
    record["compact_small_max_logit_diff"] = (before - after.float()).abs().max().item()
    for batch in [1, 8]:
        for length in [32, 256]:
            timing(small, batch, length, "compact_small")
record["completed"] = True
save()
