"""Offline prompt-only extraction, with a parity gate against archived states."""

import json
import os
import time
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForCausalLM

root = Path(os.environ["STAGE_B_ROOT"])
archive = Path(os.environ["PREFILL_REFERENCE"])
freeze = json.loads((root/"freeze.json").read_text())
prefixes = json.loads((archive/"prefix-selection.json").read_text())
reference = np.load(archive/"features.npz")["X"][:,0]
model = AutoModelForCausalLM.from_pretrained(os.environ["LARB_MODEL_PATH"],
    dtype=torch.bfloat16,attn_implementation="sdpa",local_files_only=True).to("cuda").eval()

@torch.inference_mode()
def feature(ids):
    tokens = torch.tensor([ids],device="cuda")
    torch.cuda.synchronize()
    start = time.monotonic()
    hidden = model.model(input_ids=tokens,attention_mask=torch.ones_like(tokens),
                         use_cache=False).last_hidden_state[0,-1]
    vector = hidden.float().cpu().numpy()
    return vector, time.monotonic()-start

checks=[]
for i in (0, len(reference)//2, len(reference)-1):
    vector,_ = feature(prefixes[i]["prompt"])
    expected=reference[i]
    error=float(np.linalg.norm(vector-expected)/np.linalg.norm(expected))
    similarity=float(vector@expected/(np.linalg.norm(vector)*np.linalg.norm(expected)))
    checks.append(dict(index=i,relative_l2=error,cosine=similarity))
(root/"prefill-parity.json").write_text(json.dumps(checks,indent=2)+"\n")
assert all(x["relative_l2"] <= .02 and x["cosine"] >= .999 for x in checks),checks
vectors,times=zip(*(feature(row["solver_ids"]) for row in freeze["questions"]))
assert np.isfinite(vectors).all()
np.savez(root/"prefill.npz",X=np.stack(vectors),seconds=times,
         keys=[row["question_id"] for row in freeze["questions"]])
