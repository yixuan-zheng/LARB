"""Real GPU, cohort-batched, FIFO overload replay. Not continuous batching."""

import argparse, json, time, random, re, string, types, statistics, hashlib, collections
from pathlib import Path
import torch
import torch.nn.functional as F
from transformers import AutoTokenizer, Gemma3nForConditionalGeneration

p = argparse.ArgumentParser()
p.add_argument("--root", required=True)
a = p.parse_args()
root = Path(a.root)
out = root / "results"
out.mkdir(exist_ok=True)
REV = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
torch.set_num_threads(4)
torch.manual_seed(7)
model = (
    Gemma3nForConditionalGeneration.from_pretrained(
        "google/gemma-3n-E4B", revision=REV, dtype=torch.bfloat16, local_files_only=True
    )
    .eval()
    .to("cuda")
)
tok = AutoTokenizer.from_pretrained(
    "google/gemma-3n-E4B", revision=REV, local_files_only=True
)
tok.padding_side = "left"
presets = json.loads((root / "code/presets.json").read_text())["presets"]
layers = model.model.language_model.layers


def width_forward(m, x):
    w = m.active_width
    g = F.linear(x, m.gate_proj.weight[:w])
    if m.activation_sparsity > 0:
        g = m._gaussian_topk(g)
    return F.linear(
        m.act_fn(g) * F.linear(x, m.up_proj.weight[:w]), m.down_proj.weight[:, :w]
    )


for l in layers:
    l.mlp.forward = types.MethodType(width_forward, l.mlp)


def select(mode):
    for l, w in zip(layers, presets[mode]["ffn_hidden_dims"]):
        l.mlp.active_width = w


def normalize(s):
    return " ".join(
        re.sub(
            r"\b(a|an|the)\b",
            " ",
            s.lower().translate(str.maketrans("", "", string.punctuation)),
        ).split()
    )


def score(text, answers):
    pred = normalize(text)
    em = int(any(pred == normalize(x) for x in answers))
    f1 = 0
    for ans in answers:
        x, y = pred.split(), normalize(ans).split()
        common = sum((collections.Counter(x) & collections.Counter(y)).values())
        f1 = max(f1, 2 * common / (len(x) + len(y)) if x and y else float(x == y))
    return em, f1


def flatten(file):
    data = json.loads(file.read_text())
    r = []
    for article in data["data"]:
        for para in article["paragraphs"]:
            for q in para["qas"]:
                r.append(
                    {
                        "id": q["id"],
                        "context": para["context"],
                        "question": q["question"],
                        "answers": [x["text"] for x in q["answers"]],
                        "article": article["title"],
                    }
                )
    return r


instruction = "Answer the question using the target passage. Write only the short answer, then a newline.\nExample: Passage: Paris is the capital of France. Question: What is the capital of France?\nAnswer: Paris\nExample: Passage: A week has seven days. Question: How many days does a week have?\nAnswer: seven\n"


def prepare(data, n, seed):
    rng = random.Random(seed)
    rng.shuffle(data)
    items = []
    distractor = "Unrelated passage: " + data[-1]["context"] + "\n"
    for row in data:
        target = 256 if len(items) % 2 == 0 else 1024
        tail = (
            "\nTarget passage: "
            + row["context"]
            + "\nQuestion: "
            + row["question"]
            + "\nAnswer:"
        )
        core = instruction + tail
        ids = tok.encode(core)
        if len(ids) > target:
            continue
        # Add irrelevant document text before the intact target passage; prompt construction frozen before evaluation.
        room = target - len(ids)
        extra = ""
        if room > 8:
            fill = tok.encode(distractor * 20, add_special_tokens=False)[: room - 4]
            extra = tok.decode(fill) + "\n"
        prompt = instruction + extra + tail
        ids = tok.encode(prompt)
        item = {**row, "input_ids": ids, "bucket": target, "prompt_tokens": len(ids)}
        items.append(item)
        if len(items) == n:
            break
    assert len(items) == n
    return items


w = json.loads((root / "data/workload.json").read_text())
dev = w["development"]
evaluation = w["evaluation"]
end_ids = set([tok.eos_token_id])
pad = tok.pad_token_id


@torch.inference_mode()
def generate(batch, prefill, decode, epoch=None, width_policy=None):
    ids = [x["input_ids"] for x in batch]
    length = max(map(len, ids))
    x = torch.tensor([[pad] * (length - len(v)) + v for v in ids], device="cuda")
    mask = (x != pad).long()
    select(prefill)
    r = model(
        input_ids=x[:, :-1],
        attention_mask=mask[:, :-1],
        use_cache=True,
        logits_to_keep=1,
    )
    select(decode)
    r = model(
        input_ids=x[:, -1:],
        attention_mask=mask,
        past_key_values=r.past_key_values,
        use_cache=True,
        logits_to_keep=1,
    )
    generated = [[] for _ in batch]
    times = [[] for _ in batch]
    histories = [[] for _ in batch]
    current_width = decode
    finished = [False] * len(batch)
    truncated = [True] * len(batch)
    for step in range(32):
        nxt = r.logits[:, -1].argmax(-1)
        values = nxt.tolist()
        now = time.perf_counter()
        for i, v in enumerate(values):
            if finished[i]:
                continue
            times[i].append(now if epoch is None else now - epoch)
            histories[i].append(current_width)
            if v in end_ids:
                finished[i] = True
                truncated[i] = False
            else:
                generated[i].append(v)
                if "\n" in tok.decode(generated[i]):
                    finished[i] = True
                    truncated[i] = False
        if all(finished):
            break
        mask = torch.cat(
            [mask, torch.ones((len(batch), 1), dtype=mask.dtype, device="cuda")], 1
        )
        if width_policy is not None:
            current_width = width_policy(step + 1)
            select(current_width)
        r = model(
            input_ids=nxt[:, None],
            attention_mask=mask,
            past_key_values=r.past_key_values,
            use_cache=True,
            logits_to_keep=1,
        )
    rows = []
    for i, item in enumerate(batch):
        raw = tok.decode(generated[i], skip_special_tokens=True)
        answer = raw.split("\n")[0].strip()
        em, f1 = score(answer, item["answers"])
        rows.append(
            {
                "id": item["id"],
                "bucket": item["bucket"],
                "prompt_tokens": item["prompt_tokens"],
                "answer": answer,
                "raw_output": raw,
                "references": item["answers"],
                "em": em,
                "f1": f1,
                "tokens": len(generated[i]),
                "truncated": truncated[i],
                "token_times": times[i],
                "prefill": prefill,
                "decode": decode,
                "token_widths": histories[i],
                "switches": sum(a != b for a, b in zip(histories[i], histories[i][1:])),
            }
        )
    return rows


def save(name, data):
    (out / name).write_text(json.dumps(data, indent=2) + "\n")


record = {
    "revision": REV,
    "gpu": torch.cuda.get_device_name(),
    "torch": torch.__version__,
    "runtime": "eager HF PyTorch; FIFO cohort batches; no continuous batching; decode-policy extension",
    "slo": {"ttft_ms": 1000, "max_itl_ms": 200},
    "quality": {},
    "traces": [],
}
save("experiment.json", record)
print("HARNESS warmup", flush=True)
generate(dev[:2], "large", "large")
warm = generate(dev[:2], "small", "large")
assert all(
    x["token_times"] and x["prefill"] == "small" and x["decode"] == "large"
    for x in warm
)
source = json.loads((out / "calibration-source.json").read_text())
record["calibration"] = source["calibration"]
rate = record["calibration"]["lambda0_requests_s"]
save("experiment.json", record)
# Quality screen independent of arrival timing; all three fixed paths on paired examples.
schedules = [
    ("large", "large", "large", None),
    ("small", "small", "small", None),
    ("large_to_small", "large", "large", lambda step: "large" if step < 2 else "small"),
    ("small_to_large", "small", "small", lambda step: "small" if step < 2 else "large"),
    (
        "alternating",
        "large",
        "large",
        lambda step: "large" if (step // 2) % 2 == 0 else "small",
    ),
]
for label, pre, dec, callback in schedules:
    rows = []
    for i in range(0, 200, 8):
        rows.extend(generate(evaluation[i : i + 8], pre, dec, width_policy=callback))
    save("quality_" + label + ".json", rows)
    record["quality"][label] = {
        "em": sum(x["em"] for x in rows) / 200,
        "f1": sum(x["f1"] for x in rows) / 200,
        "truncated": sum(x["truncated"] for x in rows),
        "requests_with_switch": sum(x["switches"] > 0 for x in rows),
    }
    save("experiment.json", record)
    print("QUALITY", label, record["quality"][label], flush=True)
# Fixed count trace, 20-arrival segments alternating light and overload. Poisson arrivals within each segment.
for seed in [11, 22, 33]:
    trace = json.loads((out / f"trace_{seed}.json").read_text())
    policies = ["large", "small", "request", "iteration"]
    random.Random(seed + 100).shuffle(policies)
    for policy in policies:
        begin = time.perf_counter()
        pending = []
        next_arrival = 0
        rows = []
        ops = []
        max_queue = 0
        wave = 0
        while next_arrival < len(trace) or pending:
            elapsed = time.perf_counter() - begin
            while (
                next_arrival < len(trace)
                and trace[next_arrival]["arrival_s"] <= elapsed
            ):
                pending.append(trace[next_arrival])
                next_arrival += 1
            max_queue = max(max_queue, len(pending))
            if not pending:
                time.sleep(
                    min(0.01, max(0, trace[next_arrival]["arrival_s"] - elapsed))
                )
                continue
            # Batching delay never exceeds 10 ms from the oldest ready request.
            if len(pending) < 8 and elapsed - pending[0]["arrival_s"] < 0.01:
                time.sleep(0.001)
                continue
            oldest = elapsed - pending[0]["arrival_s"]
            pressure = len(pending) >= 4 or oldest >= 0.25
            pre = (
                "small"
                if policy == "small"
                or (policy in ["request", "iteration"] and pressure)
                else "large"
            )
            dec = pre
            # Oldest request chooses the bucket; FIFO within that bucket, up to eight.
            bucket = evaluation[pending[0]["index"]]["bucket"]
            chosen = [
                i
                for i, x in enumerate(pending)
                if evaluation[x["index"]]["bucket"] == bucket
            ][:8]
            count = len(chosen)
            selected = [pending[i] for i in chosen]
            for i in reversed(chosen):
                del pending[i]
            start = time.perf_counter() - begin

            def online_width(step):
                now = time.perf_counter() - begin
                waiting = pending + [
                    x for x in trace[next_arrival:] if x["arrival_s"] <= now
                ]
                busy = len(waiting) >= 4 or (
                    bool(waiting) and now - min(x["arrival_s"] for x in waiting) >= 0.25
                )
                return "small" if busy else "large"

            generated = generate(
                [evaluation[x["index"]] for x in selected],
                pre,
                dec,
                begin,
                width_policy=online_width if policy == "iteration" else None,
            )
            finish = time.perf_counter() - begin
            ops.append(
                {
                    "wave": wave,
                    "start_s": start,
                    "finish_s": finish,
                    "batch": count,
                    "bucket": bucket,
                    "pending_before": len(pending) + count,
                    "oldest_wait_s": oldest,
                    "pressure": pressure,
                    "prefill": pre,
                    "decode": dec,
                }
            )
            wave += 1
            for request, result in zip(selected, generated):
                times = result.pop("token_times")
                ttft = (times[0] - request["arrival_s"]) * 1000
                itl = max([(b - a) * 1000 for a, b in zip(times, times[1:])], default=0)
                passed = ttft <= 1000 and itl <= 200
                rows.append(
                    {
                        **result,
                        **request,
                        "ttft_ms": ttft,
                        "max_itl_ms": itl,
                        "completion_s": times[-1],
                        "latency_pass": passed,
                        "quality_slo_pass": passed and bool(result["em"]),
                    }
                )
        end = time.perf_counter() - begin
        summary = {
            "seed": seed,
            "policy": policy,
            "requests": len(rows),
            "wall_seconds": end,
            "goodput": sum(x["quality_slo_pass"] for x in rows) / end,
            "latency_goodput": sum(x["latency_pass"] for x in rows) / end,
            "throughput": len(rows) / end,
            "em": sum(x["em"] for x in rows) / len(rows),
            "slo_pass_rate": sum(x["latency_pass"] for x in rows) / len(rows),
            "small_prefill_fraction": sum(x["prefill"] == "small" for x in rows)
            / len(rows),
            "requests_with_switch": sum(x["switches"] > 0 for x in rows),
            "total_switches": sum(x["switches"] for x in rows),
            "max_queue": max_queue,
            "mean_ttft_ms": statistics.mean(x["ttft_ms"] for x in rows),
            "p95_ttft_ms": sorted(x["ttft_ms"] for x in rows)[
                int(0.95 * (len(rows) - 1))
            ],
            "mean_batch": statistics.mean(x["batch"] for x in ops),
        }
        save(
            f"replay_{seed}_{policy}.json",
            {"summary": summary, "requests": rows, "operations": ops},
        )
        record["traces"].append(summary)
        save("experiment.json", record)
        print("REPLAY", summary, flush=True)
record["completed"] = True
save("experiment.json", record)
print("COMPLETE", flush=True)
