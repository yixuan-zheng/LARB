"""Run only budget selection. Read solver outcomes exclusively for development examples."""

import json
import os
import time
from pathlib import Path

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.sampling_params import StructuredOutputsParams

root = Path(os.environ["AUDIT_ROOT"])
source = Path.home() / "scratch/larb-math-repair-20261118"
freeze = json.loads((source / "freeze.json").read_text())
budgets = freeze["budgets"]
labels = list(budgets)
questions = freeze["smoke"]
dev = [question for i, question in enumerate(questions) if i % 3 == 0]
held = [question for i, question in enumerate(questions) if i % 3 != 0]
assert len(dev) == 8 and len(held) == 16
assert len({q["question_id"] for q in questions}) == 24

examples = {}
for q in dev:
    qid = q["question_id"]
    for label, cap in budgets.items():
        outcomes = [json.loads((source / "smoke/solves" /
                     f"smoke--fixed{cap}--{qid}--{seed}.json").read_text())
                    for seed in freeze["seeds"]]
        if all(r["correct"] for r in outcomes):
            examples.setdefault(label, q)
            break

rubric = ("Allocate internal reasoning tokens to a Qwen3-4B solver. "
          "2K (2048): a familiar result or one short derivation; "
          "4K (4096): several linked steps or a short case split; "
          "6K (6096): multiple nontrivial deductions, a substantial case split, or checks; "
          "8K (8192): sustained search, a tricky proof, or several approaches worth testing. "
          "Choose the tier that best matches the work involved. Do not solve the problem. "
          "Reply with just 2K, 4K, 6K, or 8K.")
difficulty = ("Classify the difficulty for a 4B math solver, considering the number of "
              "dependent deductions, search, and verification. A means short and routine; "
              "B means multistep with a clear approach; C means complex and error-prone; "
              "D means substantial search or an unclear approach. Do not solve. "
              "Reply only A, B, C, or D.")
demos = "\n\n".join(f"Example problem:\n{q['problem']}\nBudget: {label}"
                       for label, q in examples.items())
print(json.dumps({"development_ids": [q["question_id"] for q in dev],
                  "held_ids": [q["question_id"] for q in held],
                  "examples": {k:q["question_id"] for k,q in examples.items()}}), flush=True)

model = os.environ["AUDIT_MODEL"]
tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
engine = LLM(model=model, dtype="bfloat16", max_model_len=12288, max_num_seqs=4,
             max_num_batched_tokens=8192, gpu_memory_utilization=0.65,
             enforce_eager=True, enable_prefix_caching=False, generation_config="vllm")

def render(prompt):
    return tokenizer.apply_chat_template([{"role":"user","content":prompt}],
        tokenize=True, add_generation_prompt=True, enable_thinking=False)

variants = {
    "original_reverse": (freeze["selector_prompt"], list(reversed(labels)), budgets),
    "rubric": (rubric, labels, budgets),
    "examples": (rubric + "\n\n" + demos, labels, budgets),
    "difficulty": (difficulty, list("ABCD"), dict(zip("ABCD", budgets.values()))),
}
for name, (prompt, choices, mapping) in variants.items():
    params = SamplingParams(temperature=0, max_tokens=8,
                            structured_outputs=StructuredOutputsParams(choice=choices))
    engine.generate([{"prompt_token_ids":render(prompt+"\n\nProblem:\nCompute 2+2.")}],
                    params, use_tqdm=False)
    with (root / f"{name}.jsonl").open("w") as output:
        for q in held:
            ids = render(prompt + "\n\nProblem:\n" + q["problem"])
            started = time.monotonic()
            result = engine.generate([{"prompt_token_ids":ids}], params, use_tqdm=False)[0].outputs[0]
            label = result.text.strip()
            row = dict(question_id=q["question_id"], label=label, valid=label in mapping,
                       budget=mapping.get(label, 4096), seconds=time.monotonic()-started,
                       input_tokens=len(ids), output_tokens=len(result.token_ids))
            output.write(json.dumps(row)+"\n")
            output.flush()
