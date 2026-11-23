"""Exercise the policy-gradient path without producing a training checkpoint."""
import json
import math
import os
import time
from pathlib import Path

import torch
from torch import nn
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint
from transformers import AutoModelForCausalLM, AutoTokenizer

from probe import MODES, mode_ids, prompt_ids


class LoRA(nn.Module):
    def __init__(self, base, rank=16):
        super().__init__()
        self.base = base
        self.down = nn.Linear(base.in_features, rank, bias=False, device="cuda")
        self.up = nn.Linear(rank, base.out_features, bias=False, device="cuda")
        nn.init.zeros_(self.up.weight)

    def forward(self, inputs):
        return self.base(inputs) + self.up(self.down(inputs.float())).to(inputs.dtype)


def main():
    torch.manual_seed(123)
    path = os.environ["LARB_MODEL_PATH"]
    tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
    start = time.monotonic()
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16,
        local_files_only=True, attn_implementation="sdpa").to("cuda").train()
    model.requires_grad_(False)
    model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
    model.config.use_cache = False
    for block in model.model.layers:
        attention = block.self_attn
        attention.q_proj = LoRA(attention.q_proj)
        attention.v_proj = LoRA(attention.v_proj)
    params = [parameter for parameter in model.parameters() if parameter.requires_grad]
    optimizer = torch.optim.AdamW(params, lr=1e-4)
    actions = torch.tensor(list(mode_ids(tokenizer).values()), device="cuda")

    def root_logprobs(problem):
        ids = torch.tensor([prompt_ids(tokenizer, problem)], device="cuda")
        return model(ids, logits_to_keep=1).logits[0, 0, actions].float().log_softmax(-1)

    # Synthetic targets test credit assignment independently
    # of math skill. Every digit is rewarded on a different input.
    tasks = [f"For this controlled exercise, the desired effort is {name}. Solve 1+1."
             for name in MODES]
    with torch.no_grad():
        before = torch.stack([root_logprobs(task) for task in tasks])
    for _ in range(32):
        optimizer.zero_grad()
        for index, task in enumerate(tasks):
            logp = root_logprobs(task)
            # A supervised positive control isolates routing credit from PPO
            # clipping and changes in probability outside the action set.
            loss = -logp[index] / len(tasks)
            loss.backward()
        optimizer.step()
    with torch.no_grad():
        after = torch.stack([root_logprobs(task) for task in tasks])
    improvement = (after.diag() - before.diag()).tolist()

    # Replay real forced-mode trajectories. The controller cue is an
    # environment action, so only the mode and sampled response receive loss.
    records = [json.loads(file.read_text()) for file in sorted(Path("solves").glob("*.json"))]
    longest = max((row for row in records if row["mode"] in MODES), key=lambda row: len(row["output"]))
    group = [row for row in records if row["question_id"] == longest["question_id"] and row["mode"] in MODES]

    def token_logprobs(row):
        response = [row["label"], *row["output"]]
        excluded = {position + 1 for position in row["forced_positions"]}
        indices = [i for i in range(len(response)) if i not in excluded]
        assert indices[0] == 0
        if row.get("binding_fixture"):
            bridge = row["bridge_tokens"]
            cap = MODES[row["mode"]][1]
            cue = row["cue_tokens"]
            first_answer = 1 + bridge + cap + cue
            expected = [0, *range(1 + bridge, 1 + bridge + cap),
                        *range(first_answer, len(response))]
            assert indices == expected and first_answer < len(response)
        ids = torch.tensor([row["prompt"] + response], device="cuda")
        hidden = model.model(ids, use_cache=False).last_hidden_state[0]
        pos = torch.tensor(indices, device="cuda")
        predictors = hidden[len(row["prompt"]) - 1 + pos]
        targets = ids[0, len(row["prompt"]) + pos]

        def selected_logp(states, labels):
            logits = model.lm_head(states).float()
            return -F.cross_entropy(logits, labels, reduction="none")

        return torch.cat([checkpoint(selected_logp, states, labels, use_reentrant=False)
                          for states, labels in zip(predictors.split(128), targets.split(128))])

    def reward(row):
        base, discount = {"Low": (1.3, .99984), "Medium": (1.2, .99994), "High": (1., 1.)}[row["mode"]]
        return base * discount**len(row["output"]) if row["correct"] else 0.

    rewards = [reward(row) for row in group]
    center = sum(rewards) / len(rewards)
    # A zero-variance math group legitimately yields zero gradient. Use a
    # synthetic positive advantage on that trajectory for a timing check.
    synthetic_timing = not any(value != center for value in rewards)
    optimizer.zero_grad()
    torch.cuda.reset_peak_memory_stats()
    torch.cuda.synchronize()
    started = time.monotonic()
    root_grads = []
    tokens = 0
    for row, value in zip(group, rewards):
        advantage = 1. if synthetic_timing else value-center
        logps = token_logprobs(row)
        assert torch.isfinite(logps).all()
        logps.retain_grad()
        # At the first update the old and current log probabilities coincide.
        loss = -(logps - logps.detach()).exp().mean() * advantage / len(group)
        loss.backward()
        root_grads.append(float(logps.grad[0]))
        tokens += len(row["output"]) + len(row["prompt"]) + 1
    norm = float(torch.nn.utils.clip_grad_norm_(params, 1.))
    optimizer.step()
    torch.cuda.synchronize()
    result = dict(controlled_log_probability_lift=improvement, math_group_rewards=rewards,
        synthetic_timing_advantage=synthetic_timing, root_gradients=root_grads,
        math_gradient_norm=norm, group_seconds=time.monotonic()-started,
        training_input_tokens=tokens, longest_sequence=len(longest["prompt"])+len(longest["output"])+1,
        peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
        total_seconds=time.monotonic()-start)
    Path("training-summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result), flush=True)
    assert all(lift > 0 for lift in improvement) and any(root_grads) and math.isfinite(norm) and norm > 0
    assert not synthetic_timing, "The sampled group provided no verifiable reward contrast"


if __name__ == "__main__":
    main()
