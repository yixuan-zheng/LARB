"""Bounded multi-question GRPO with vLLM rollouts and local LoRA updates."""
import json
import math
import os
import random
import statistics
import time
from collections import Counter
from pathlib import Path

import torch
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

from gate import export_adapter
from larb_scaled import analysis, grading
from screen import ANSWER_CAP, MODES, NAMES, Screen, reward


def append(path, row):
    with Path(path).open("a") as handle:
        print(json.dumps(row), file=handle)


class Followup(Screen):
    def __init__(self, model):
        memory = torch.cuda.get_device_properties(0).total_memory / 2**30
        self.engine = LLM(model=model, dtype="bfloat16", max_model_len=12288,
            gpu_memory_utilization=.56 if memory >= 70 else .47,
            enable_lora=True, max_lora_rank=16, max_loras=1, max_cpu_loras=2,
            enforce_eager=True, enable_prefix_caching=False, generation_config="vllm",
            max_num_seqs=12, max_num_batched_tokens=8192, logprobs_mode="processed_logprobs",
            logits_processors=["larb_scaled.controller:PressureProcessor"],
            scheduler_cls="larb_scaled.controller.QueueAuditScheduler")
        super().__init__(model)
        self.batch_id = 0
        self.adapters = Path(os.environ["LARB_OUT"]).parent / "adapters"
        self.adapters.mkdir()
        self.previous_path = None

    def refresh(self, step):
        name = f"step-{step}"
        path = self.adapters / name
        export_adapter({k:v.detach().cpu() for k,v in self.weights.items()}, path)
        self.adapter = LoRARequest(name, step+1, str(path))
        if self.previous_path is not None:
            for file in self.previous_path.iterdir():
                file.unlink()
            self.previous_path.rmdir()
        self.previous_path = path

    def roll(self, cases, *, sample, seed):
        self.batch_id += 1
        params, inputs, info = [], [], []
        for i, (row, mode, root_logp) in enumerate(cases):
            prompt, bridges = self.parts(row)
            bridge = bridges[mode]
            label = int(self.actions[mode])
            tokens = prompt+[label]+bridge
            cap = MODES[NAMES[mode]][1]
            key = f"mixed--fixed--{self.batch_id}--{i}"
            extra = None if mode == 0 else {"larb":dict(key=key, policy="fixed", budget=cap,
                cue=self.contract.cue, close_id=self.contract.close_id, eos_id=self.contract.eos_id,
                answer_cap=ANSWER_CAP, contract=self.contract.name, arrival_ts=time.monotonic())}
            params.append(SamplingParams(temperature=1. if sample else 0.,
                top_p=1., top_k=-1, seed=seed+i, logprobs=1 if sample else None,
                skip_special_tokens=False, max_tokens=cap+len(self.contract.cue)+ANSWER_CAP+1
                if mode else ANSWER_CAP, extra_args=extra))
            if len(tokens)+params[-1].max_tokens > 12288:
                raise ValueError(f"Over-context question {row['question_id']}")
            inputs.append({"prompt_token_ids":tokens})
            info.append((row,mode,root_logp,prompt,bridge,label,cap,key))
        start = time.monotonic()
        results = self.engine.generate(inputs, params, lora_request=self.adapter, use_tqdm=False)
        seconds = time.monotonic()-start
        records = []
        for result, (row,mode,root_logp,prompt,bridge,label,cap,key) in zip(results,info,strict=True):
            output = result.outputs[0]
            seq = list(output.token_ids)
            state = {} if mode == 0 else json.loads(
                (Path(os.environ["LARB_OUT"])/"request-state"/f"{key}.json").read_text())
            bound = state.get("cue_start")
            if bound is not None and bound != cap:
                raise RuntimeError(f"Cap mismatch for {key}")
            close, eos = self.contract.close_id, self.contract.eos_id
            audit = analysis.audit_completion(dict(token_ids=[close,*seq] if mode == 0 else seq,
                complete=result.finished, close_id=close, eos_id=eos, cue_ids=self.contract.cue,
                answer_cap=ANSWER_CAP, capped=state.get("cap")), bound)
            first_close = seq.index(close) if close in seq else -1
            answer_ids = seq[first_close+1:] if mode else seq
            answer = self.tokenizer.decode(answer_ids, skip_special_tokens=True)
            correct = audit["normal"] and self.opening not in answer_ids and grading.grade(
                answer,row["answer"],use_math_verify=False)["correct"]
            forced = set(range(1,1+len(bridge)))
            if bound is not None:
                start = 1+len(bridge)+bound
                forced.update(range(start,start+len(self.contract.cue)))
            if state.get("cap") == "answer_cap" and seq[-1:] == [eos]:
                forced.add(len(bridge)+len(seq))
            response = [label,*bridge,*seq]
            entry = dict(mode=mode, correct=bool(correct), normal=audit["normal"],
                total_tokens=len(prompt)+len(response), decode_tokens=len(seq),
                reasoning_tokens=audit["thinking_tokens"], cap_bound=bound is not None,
                prompt=prompt, response=response, masked=sorted(forced))
            if sample:
                entry["behavior"] = [root_logp,*[
                    step[token].logprob for i,(step,token) in enumerate(zip(output.logprobs,seq,strict=True))
                    if 1+len(bridge)+i not in forced]]
            records.append(entry)
        return records, seconds

    def update(self, rows, advantages, *, warmup):
        self.model.train()
        self.optimizer.zero_grad()
        count = sum(len(row["behavior"]) for row in rows)
        error = []
        for row, advantage in zip(rows,advantages,strict=True):
            logp = self.logprobs(row)
            behavior = torch.as_tensor(row["behavior"],device=logp.device)
            assert logp.shape == behavior.shape
            delta = logp-behavior
            error.append(float(delta.detach().abs().mean()))
            if not advantage:
                continue
            # Balanced forced exploration is a separate initialization phase.
            ratio = (logp-logp.detach()).exp() if warmup else delta.exp()
            loss = -torch.minimum(ratio*advantage,ratio.clamp(.8,1.2)*advantage).sum()/count
            loss.backward()
        if max(error) > .15:
            raise RuntimeError(f"Behavior likelihood parity failed: {max(error):.4f}")
        norm = float(torch.nn.utils.clip_grad_norm_(self.weights.values(),1.))
        if not math.isfinite(norm):
            raise RuntimeError("Nonfinite gradient")
        if norm:
            self.optimizer.step()
        return norm, max(error)


def train(screen, rows, end, group_size, questions_per_step, warmup_steps):
    done = 0
    max_step = len(rows)//questions_per_step
    for offset in range(0,len(rows),questions_per_step):
        if time.time() > end-1200:
            break
        step = offset//questions_per_step+1
        started = time.monotonic()
        screen.refresh(step-1)
        warm = step <= warmup_steps
        cases, free_modes = [], []
        for index,row in enumerate(rows[offset:offset+questions_per_step]):
            logits = screen.route_logits(row).log_softmax(-1)
            torch.manual_seed(7000+offset+index)
            forced = [0,1,2]*((group_size-2)//3) if warm else []
            drawn = torch.multinomial(logits.exp(),group_size-len(forced),replacement=True).tolist()
            cases.extend((row,mode,float(logits[mode])) for mode in forced+drawn)
            free_modes.extend(drawn)
        outcomes, seconds = screen.roll(cases,sample=True,seed=30000+offset*group_size)
        adv = []
        counts = Counter(free_modes)
        beta = .2*max(0.,1-step/(.8*max_step))
        for start in range(0,len(outcomes),group_size):
            group = outcomes[start:start+group_size]
            rewards = [reward(row) for row in group]
            for row,value in zip(group,rewards,strict=True):
                nudge = beta*(1/3-counts[row["mode"]]/len(free_modes))
                nudge = nudge if (nudge > 0) == row["correct"] else 0.
                adv.append(value-statistics.mean(rewards)+nudge)
        gradient, error = screen.update(outcomes,adv,warmup=warm)
        screen.save(step)
        if step % 8 == 0 and step not in (8,16,24):
            torch.save({"step":step,"adapter":{k:v.detach().cpu() for k,v in screen.weights.items()}},
                       f"adapter-step-{step:02d}.pt")
        done = step
        record = dict(step=step,warmup=warm,free_modes=dict(counts),rollout_seconds=seconds,
            total_seconds=time.monotonic()-started, tokens=sum(row["decode_tokens"] for row in outcomes),
            correct=sum(row["correct"] for row in outcomes),likelihood_error=error,gradient_norm=gradient)
        append("training.jsonl",record)
        print(json.dumps(record),flush=True)
    return done


def evaluate(screen, rows, draws, end, output="evaluation.jsonl"):
    count = 0
    for offset in range(0,len(rows),4 if draws == 1 else 2):
        if time.time() > end-900:
            break
        width = 4 if draws == 1 else 2
        cohort = rows[offset:offset+width]
        cases, routes = [], []
        for row in cohort:
            start = time.monotonic()
            logits = screen.route_logits(row)
            routes.append((int(logits.argmax()),time.monotonic()-start,len(screen.parts(row)[0])))
            cases.extend((row,mode,0.) for _ in range(draws) for mode in range(3))
        results, seconds = screen.roll(cases,sample=draws>1,seed=73000+offset*6)
        for i,(row,(mode,route_wall,prefill)) in enumerate(zip(cohort,routes,strict=True)):
            compact = []
            for action in range(3):
                records = results[i*draws*3+action:(i+1)*draws*3:3]
                compact.append(dict(correct=statistics.mean(float(r["correct"]) for r in records),
                                    total_tokens=statistics.mean(r["total_tokens"] for r in records)))
            append(output,dict(question_id=row["question_id"],stratum=row["source"],
                problem_words=len(row["problem"].split()),
                selected=mode,route_seconds=route_wall,route_prefill_tokens=prefill,
                batch_seconds=seconds/len(cohort),arms=compact))
            count += 1
        print(f"Evaluation {count}/{len(rows)}",flush=True)
    return count


if __name__ == "__main__":
    scope = os.environ["LARB_SCOPE"]
    plan = json.loads(Path("freeze.json").read_text())
    rows = plan["train"]
    test = plan["evaluation"]
    if scope == "reduced":
        rows = [row for source in ("gsm8k","math","omni") for row in
                [r for r in rows if r["source"] == source][:32]]
        test = [row for source in ("gsm8k","math","omni") for row in
                [r for r in test if r["source"] == source][:32]]
        random.Random(42).shuffle(rows)
        random.Random(43).shuffle(test)
    groups, width, warm, draws = (8,8,16,2) if scope=="full" else (6,4,6,1)
    screen = Followup(os.environ["LARB_MODEL_PATH"])
    complete = train(screen,rows,int(os.environ["TRAIN_END_EPOCH"]),groups,width,warm)
    Path("training-status.json").write_text(json.dumps(dict(planned=len(rows)//width,complete=complete))+"\n")
    if not complete:
        raise RuntimeError("No checkpoint available")
    screen.refresh(complete)
    passed = evaluate(screen,test,draws,int(os.environ["EVAL_END_EPOCH"]))
    Path("evaluation-status.json").write_text(json.dumps(dict(planned=len(test),complete=passed))+"\n")
    if passed != len(test):
        raise RuntimeError("Evaluation incomplete")
    evaluate(screen,plan["development"][:24 if scope == "reduced" else 48],1,
             int(os.environ["EVAL_END_EPOCH"]),"development.jsonl")
