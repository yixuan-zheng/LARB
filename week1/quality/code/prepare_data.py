"""Freeze the GSM8K task: few-shot prompt, dev/held-out/diagnostic splits, and the quality contract.

CPU only. Writes everything the GPU scripts need into manifests/, so PACE never
has to download the dataset.
"""
import hashlib
import json
import random
import re

import datasets

from common import MANIFESTS, new_run_id, run_manifest, write_json

DATASET = "openai/gsm8k"
DATASET_REVISION = "740312add88f781978c0658806c59bc2815b9866"
SEED = 6222
N_DEV, N_HELDOUT, N_DIAGNOSTIC = 250, 250, 50

# standard 8-shot chain-of-thought exemplars (Wei et al., 2022); hand-written, not from the test set
FEWSHOT = [
    ("There are 15 trees in the grove. Grove workers will plant trees in the grove today. After they are done, there will be 21 trees. How many trees did the grove workers plant today?",
     "There are 15 trees originally. Then there were 21 trees after some more were planted. So there must have been 21 - 15 = 6. The answer is 6."),
    ("If there are 3 cars in the parking lot and 2 more cars arrive, how many cars are in the parking lot?",
     "There are originally 3 cars. 2 more cars arrive. 3 + 2 = 5. The answer is 5."),
    ("Leah had 32 chocolates and her sister had 42. If they ate 35, how many pieces do they have left in total?",
     "Originally, Leah had 32 chocolates. Her sister had 42. So in total they had 32 + 42 = 74. After eating 35, they had 74 - 35 = 39. The answer is 39."),
    ("Jason had 20 lollipops. He gave Denny some lollipops. Now Jason has 12 lollipops. How many lollipops did Jason give to Denny?",
     "Jason started with 20 lollipops. Then he had 12 after giving some to Denny. So he gave Denny 20 - 12 = 8. The answer is 8."),
    ("Shawn has five toys. For Christmas, he got two toys each from his mom and dad. How many toys does he have now?",
     "Shawn started with 5 toys. If he got 2 toys each from his mom and dad, then that is 4 more toys. 5 + 4 = 9. The answer is 9."),
    ("There were nine computers in the server room. Five more computers were installed each day, from monday to thursday. How many computers are now in the server room?",
     "There were originally 9 computers. For each of 4 days, 5 more computers were added. So 5 * 4 = 20 computers were added. 9 + 20 is 29. The answer is 29."),
    ("Michael had 58 golf balls. On tuesday, he lost 23 golf balls. On wednesday, he lost 2 more. How many golf balls did he have at the end of wednesday?",
     "Michael started with 58 golf balls. After losing 23 on tuesday, he had 58 - 23 = 35. After losing 2 more, he had 35 - 2 = 33 golf balls. The answer is 33."),
    ("Olivia has $23. She bought five bagels for $3 each. How much money does she have left?",
     "Olivia had 23 dollars. 5 bagels for 3 dollars each will be 5 x 3 = 15 dollars. So she has 23 - 15 dollars left. 23 - 15 is 8. The answer is 8."),
]
FEWSHOT_PROMPT = "".join(f"Q: {q}\nA: {a}\n\n" for q, a in FEWSHOT)


def gold_solution(answer):
    """Rewrite a GSM8K reference into the exemplar style, for teacher forcing."""
    reasoning, final = answer.split("####")
    reasoning = re.sub(r"<<[^>]*>>", "", reasoning)  # drop calculator annotations
    reasoning = " ".join(line.strip() for line in reasoning.strip().splitlines())
    return f"{reasoning} The answer is {final.strip().replace(',', '')}."


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


test = datasets.load_dataset(DATASET, "main", split="test", revision=DATASET_REVISION)
order = random.Random(SEED).sample(range(len(test)), N_DEV + N_HELDOUT)
fewshot_questions = {q for q, _ in FEWSHOT}

rows = []
for rank, index in enumerate(order):
    example = test[index]
    assert example["question"] not in fewshot_questions
    rows.append({
        "id": f"gsm8k-test-{index}",
        "split": "dev" if rank < N_DEV else "heldout",
        "diagnostic": rank < N_DIAGNOSTIC,
        "question": example["question"],
        "answer": example["answer"].split("####")[1].strip().replace(",", ""),
        "solution": gold_solution(example["answer"]),
    })

MANIFESTS.mkdir(parents=True, exist_ok=True)
(MANIFESTS / "fewshot_prompt.txt").write_text(FEWSHOT_PROMPT)
eval_path = MANIFESTS / "gsm8k_eval.jsonl"
eval_path.write_text("".join(json.dumps(row) + "\n" for row in rows))

contract = {
    "task": "GSM8K 8-shot chain-of-thought, base LM (no chat template)",
    "dataset": {"name": DATASET, "config": "main", "split": "test", "revision": DATASET_REVISION,
                "file": eval_path.name, "file_sha256": sha256(eval_path)},
    "splits": {"seed": SEED, "dev": N_DEV, "heldout": N_HELDOUT,
               "diagnostic": f"first {N_DIAGNOSTIC} dev examples (teacher-forced gold solutions)"},
    "prompt": {"file": "fewshot_prompt.txt", "file_sha256": sha256(MANIFESTS / "fewshot_prompt.txt"),
               "format": "<fewshot>Q: {question}\\nA:"},
    "decoding": {"greedy": True, "max_new_tokens": 256, "stop_strings": ["\n\n", "\nQ:"]},
    "metric": "exact match of the extracted final number against the gold answer",
    "answer_extraction": "number after the last 'The answer is'; otherwise the last number in the "
                         "output; commas, '$' and a trailing '.' removed; compared numerically",
    "quality_floor": {"reference": "static_L on the same examples",
                      "tolerance_pp": 5.0,
                      "rule": "pass (non-inferior) if the lower bound of the 95% paired bootstrap CI on "
                              "accuracy(schedule) - accuracy(static_L) is >= -5.0 pp",
                      "not_established": "point estimate >= -5.0 pp but CI lower bound < -5.0 pp",
                      "aligned_with": "team-wide Week 1 quality gate (<= 5 pp loss vs Large, 95% paired bootstrap)"},
    "uncertainty": ["Wilson 95% CI per accuracy",
                    "paired bootstrap 95% CI on the difference vs static_L (10,000 resamples, seed 6222; "
                    "examples resampled individually since GSM8K questions are independent)",
                    "exact McNemar p-value vs static_L"],
    "protocol": "schedules and restrictions are chosen on dev; held-out is evaluated once, after selection",
}
write_json(MANIFESTS / "quality_contract.json",
           {**contract, "manifest": run_manifest(new_run_id("prepare-data"), SEED,
                                                 datasets_version=datasets.__version__)})
print(f"wrote {len(rows)} examples ({N_DEV} dev, {N_HELDOUT} held-out, {N_DIAGNOSTIC} diagnostic) to {MANIFESTS}")
