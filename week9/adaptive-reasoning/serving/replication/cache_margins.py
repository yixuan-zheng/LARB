"""Extract step-24 root preferences off the scored replay path."""
import json
import os
from pathlib import Path

from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

from probe import mode_ids, template_parts

def main():
    root = Path(os.environ["REPLICATION_ROOT"])
    data = json.loads((root/"replication.json").read_text())
    rows = [row for block in data["blocks"] for row in block["questions"]]
    model = os.environ["LARB_MODEL_PATH"]
    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    actions = list(mode_ids(tokenizer).values())
    prefixes = [{"prompt_token_ids":template_parts(tokenizer,row["problem"],routed=True)[0]}
                for row in rows]
    engine = LLM(model=model,dtype="bfloat16",max_model_len=2048,enable_lora=True,max_lora_rank=16,
                 gpu_memory_utilization=.45,enforce_eager=True,logprobs_mode="processed_logprobs")
    outputs = engine.generate(prefixes,SamplingParams(max_tokens=1,temperature=1.,seed=771,
        allowed_token_ids=actions,logprobs=3),
        lora_request=LoRARequest("step24",1,os.environ["LARB_ADAPTER"]),use_tqdm=False)
    result = {}
    for row,out in zip(rows,outputs,strict=True):
        action = out.outputs[0]
        scores = action.logprobs[0]
        result[row["question_id"]] = dict(high_minus_medium_logprob=scores[actions[2]].logprob-scores[actions[1]].logprob,
            cached_choice=row.get("selected"), measured_choice=max(range(3), key=lambda i: scores[actions[i]].logprob))
    path = Path(os.environ.get("MARGIN_OUTPUT", root/"coordination-margins.json"))
    path.write_text(json.dumps(result,indent=2)+"\n")


if __name__ == "__main__":
    main()
