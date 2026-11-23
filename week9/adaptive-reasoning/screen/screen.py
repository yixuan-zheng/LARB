"""Single-seed, bounded Qwen3-4B three-mode GRPO screen."""

import json
import math
import os
import random
import statistics
import time
from collections import Counter
from pathlib import Path

import torch
from torch.nn import functional as F
from torch.utils.checkpoint import checkpoint
from transformers import AutoModelForCausalLM, AutoTokenizer, LogitsProcessor

from larb_scaled import config, grading, server
from probe import MODES, mode_ids, template_parts
from train_check import LoRA

ROOT = Path.cwd()
NAMES = tuple(MODES)
ANSWER_CAP = 2048


class EnforceCaps(LogitsProcessor):
    def __init__(self, width, caps, cue, close, eos):
        self.width = width
        self.caps = caps
        self.cue = cue
        self.close = close
        self.eos = eos
        self.cue_started = [False] * len(caps)
        self.closed_at = [0 if cap == 0 else None for cap in caps]
        self.forced = [set() for _ in caps]

    def __call__(self, ids, scores):
        step = ids.shape[1] - self.width
        for row, cap in enumerate(self.caps):
            if self.closed_at[row] is None and step and int(ids[row, -1]) == self.close:
                self.closed_at[row] = step
            if self.closed_at[row] is None and step >= cap:
                self.cue_started[row] = True
            token = None
            if self.cue_started[row] and cap <= step < cap + len(self.cue):
                token = self.cue[step - cap]
            elif self.closed_at[row] is not None and step - self.closed_at[row] >= ANSWER_CAP:
                token = self.eos
            if token is not None:
                self.forced[row].add(step)
                scores[row].fill_(-torch.inf)
                scores[row, token] = 0
        return scores


def pad(sequences, pad_id):
    width = max(map(len, sequences))
    ids = torch.tensor([[pad_id] * (width-len(seq)) + seq for seq in sequences], device="cuda")
    mask = torch.tensor([[0] * (width-len(seq)) + [1] * len(seq) for seq in sequences], device="cuda")
    return ids, mask


class Screen:
    def __init__(self, path):
        self.tokenizer = AutoTokenizer.from_pretrained(path, local_files_only=True)
        server.TOKENIZER = self.tokenizer
        self.contract = server.build_contract("legacy")
        assert self.contract.answer_cap == ANSWER_CAP
        self.actions = torch.tensor(list(mode_ids(self.tokenizer).values()), device="cuda")
        self.opening = self.tokenizer.convert_tokens_to_ids("<think>")
        self.model = AutoModelForCausalLM.from_pretrained(
            path, dtype=torch.bfloat16, local_files_only=True, attn_implementation="sdpa",
        ).to("cuda")
        self.model.requires_grad_(False)
        self.model.gradient_checkpointing_enable(gradient_checkpointing_kwargs={"use_reentrant": False})
        for layer in self.model.model.layers:
            attention = layer.self_attn
            attention.q_proj = LoRA(attention.q_proj)
            attention.v_proj = LoRA(attention.v_proj)
        self.weights = {name: param for name, param in self.model.named_parameters() if param.requires_grad}
        self.optimizer = torch.optim.AdamW(self.weights.values(), lr=8e-6)
        self.model.generation_config.pad_token_id = self.contract.eos_id

    def parts(self, row):
        root, thinking, direct = template_parts(self.tokenizer, row["problem"], routed=True)
        if self.opening not in thinking:
            thinking += self.tokenizer.encode("<think>\n", add_special_tokens=False)
        return root, (direct, thinking, thinking)

    @torch.no_grad()
    def route_logits(self, row):
        self.model.eval()
        prompt, _ = self.parts(row)
        ids = torch.tensor([prompt], device="cuda")
        return self.model(ids, use_cache=False, logits_to_keep=1).logits[0, 0, self.actions].float()

    @torch.no_grad()
    def rollout(self, row, modes, *, seed, sample):
        torch.manual_seed(seed)
        self.model.eval()
        prompt, bridges = self.parts(row)
        labels = self.actions.tolist()
        prefixes = [prompt + [labels[mode]] + bridges[mode] for mode in modes]
        batch, mask = pad(prefixes, self.contract.eos_id)
        caps = [MODES[NAMES[mode]][1] for mode in modes]
        processor = EnforceCaps(batch.shape[1], caps, self.contract.cue,
                                self.contract.close_id, self.contract.eos_id)
        started = time.monotonic()
        limits = dict(do_sample=sample)
        if sample:
            limits.update(temperature=1., top_p=1., top_k=0)
        generated = self.model.generate(
            batch, attention_mask=mask, use_cache=True, logits_processor=[processor],
            eos_token_id=self.contract.eos_id,
            max_new_tokens=max(caps) + len(self.contract.cue) + ANSWER_CAP + 1,
            **limits,
        )[:, batch.shape[1]:].tolist()
        elapsed = time.monotonic() - started
        out = []
        for index, (mode, sequence) in enumerate(zip(modes, generated)):
            eos = self.contract.eos_id
            ended = eos in sequence
            if ended:
                sequence = sequence[:sequence.index(eos)+1]
            close = self.contract.close_id
            closes = [i for i, token in enumerate(sequence) if token == close]
            close_ok = len(closes) == int(mode != 0)
            start = closes[0]+1 if closes else 0
            answer = sequence[start:]
            normal = ended and close_ok and len(answer) <= ANSWER_CAP and self.opening not in answer
            normal &= (len(sequence)-1) not in processor.forced[index]
            text = self.tokenizer.decode(answer, skip_special_tokens=True)
            correct = normal and grading.grade(text, row["answer"], use_math_verify=False)["correct"]
            bridge = bridges[mode]
            mask_idx = set(range(1, 1+len(bridge)))
            mask_idx.update(1+len(bridge)+j for j in processor.forced[index] if j < len(sequence))
            response = [labels[mode], *bridge, *sequence]
            assert 0 not in mask_idx
            charged = len(prompt) + len(response)
            out.append(dict(mode=mode, correct=bool(correct), normal=bool(normal),
                total_tokens=charged, decode_tokens=len(sequence), answer=text,
                reasoning_tokens=(caps[index] if processor.cue_started[index] else
                                  closes[0] if closes else 0),
                cap_bound=processor.cue_started[index], prompt=prompt,
                response=response, masked=sorted(mask_idx)))
        return out, elapsed

    def logprobs(self, row):
        ids = torch.tensor([row["prompt"]+row["response"]], device="cuda")
        hidden = self.model.model(ids, use_cache=False).last_hidden_state[0]
        boundary = len(row["prompt"])
        selected = [i for i in range(1, len(row["response"])) if i not in set(row["masked"])]
        root = self.model.lm_head(hidden[boundary-1])[self.actions].float().log_softmax(-1)
        positions = torch.tensor(selected, device="cuda", dtype=torch.long)
        states = hidden[boundary-1+positions]
        targets = ids[0, boundary+positions]

        def sampled_logps(states, targets):
            return -F.cross_entropy(self.model.lm_head(states).float(), targets, reduction="none")

        return torch.cat([root[row["mode"]].view(1), *[
            checkpoint(sampled_logps, states, labels, use_reentrant=False)
            for states, labels in zip(states.split(128), targets.split(128)) if len(labels)
        ]])

    def step(self, rows, advantages):
        self.model.train()
        self.optimizer.zero_grad()
        count = sum(len(r["response"])-len(r["masked"]) for r in rows)
        for row, advantage in zip(rows, advantages):
            if not advantage:
                continue
            logp = self.logprobs(row)
            ratio = (logp-logp.detach()).exp()
            # One policy update on fresh rollouts. Old and current parameters
            # coincide at this step, so the PPO ratio starts at one.
            loss = -torch.minimum(ratio*advantage, ratio.clamp(.8, 1.2)*advantage).sum()/count
            loss.backward()
        norm = float(torch.nn.utils.clip_grad_norm_(self.weights.values(), 1.))
        if not math.isfinite(norm):
            raise RuntimeError("Nonfinite GRPO gradient")
        if norm:
            self.optimizer.step()
        return norm

    def save(self, step):
        temp = ROOT / "checkpoint.tmp"
        torch.save({"step": step, "adapter": {k:v.detach().cpu() for k,v in self.weights.items()},
                    "optimizer": self.optimizer.state_dict()}, temp)
        temp.replace(ROOT / "checkpoint-latest.pt")
        if step in (8, 16, 24):
            torch.save({"step": step, "adapter": {k:v.detach().cpu() for k,v in self.weights.items()}},
                       ROOT / f"adapter-step-{step:02d}.pt")


def reward(row):
    base, decay = ((1.3, .99984), (1.2, .99994), (1., 1.))[row["mode"]]
    return base*decay**row["decode_tokens"] if row["correct"] else 0.


def train(screen, rows, end):
    routes = Counter()
    completed = 0
    for step, row in enumerate(rows, 1):
        if time.time() > end-600:
            break
        logits = screen.route_logits(row)
        torch.manual_seed(7200+step)
        drawn = torch.multinomial(logits.softmax(-1), 3 if step <= 8 else 6, replacement=True).tolist()
        modes = [0, 1, 2, *drawn] if step <= 8 else drawn
        random.Random(step).shuffle(modes)
        outcomes, seconds = screen.rollout(row, modes, seed=8900+step, sample=True)
        values = [reward(result) for result in outcomes]
        center = statistics.mean(values)
        counts = Counter(drawn)
        beta = .2*max(0, (20-step)/19)
        advantages = []
        for result, value in zip(outcomes, values):
            nudge = beta*(1/3-counts[result["mode"]]/len(drawn))
            if (nudge > 0) != result["correct"]:
                nudge = 0.
            advantages.append(value-center+nudge)
        norm = screen.step(outcomes, advantages)
        screen.save(step)
        completed = step
        routes.update(drawn)
        record = {"step":step, "question_id":row["question_id"], "modes":modes,
                  "free_modes":drawn, "free_mode_counts":dict(routes), "rewards":values,
                  "gradient_norm":norm, "rollout_seconds":seconds,
                  "outcomes":[{k:v for k,v in r.items() if k not in {"prompt","response","masked"}} for r in outcomes]}
        with (ROOT / "training.jsonl").open("a") as handle:
            print(json.dumps(record), file=handle)
        print(json.dumps({key:record[key] for key in ("step","free_modes","rewards","gradient_norm","rollout_seconds")}), flush=True)
    return completed


def evaluate(screen, rows, end):
    for index, row in enumerate(rows):
        if time.time() > end-600:
            break
        start = time.monotonic()
        logits = screen.route_logits(row)
        selected = int(logits.argmax())
        route_wall = time.monotonic()-start
        arms, seconds = screen.rollout(row, [0,1,2], seed=90100+index, sample=False)
        value = dict(question_id=row["question_id"], stratum=row["stratum"], selected=selected,
                     logits=logits.tolist(), route_seconds=route_wall, batch_seconds=seconds,
                     route_prefill_tokens=len(screen.parts(row)[0]),
                     arms=[{k:v for k,v in r.items() if k not in {"prompt","response","masked"}} for r in arms])
        with (ROOT / "evaluation.jsonl").open("a") as handle:
            print(json.dumps(value), file=handle)
        print(f"Evaluation {index+1}/{len(rows)}", flush=True)


if __name__ == "__main__":
    manifest = json.loads((ROOT / "freeze.json").read_text())
    screen = Screen(os.environ["LARB_MODEL_PATH"])
    completed = train(screen, manifest["train"], float(os.environ["TRAIN_END_EPOCH"]))
    config.write_json(ROOT / "training-status.json", {"complete_updates":completed})
    if not completed:
        raise RuntimeError("No training update completed within the time budget")
    evaluate(screen, manifest["evaluation"], float(os.environ["EVAL_END_EPOCH"]))
