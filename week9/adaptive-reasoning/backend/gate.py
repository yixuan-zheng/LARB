"""Check adapter reload, root probabilities, cap behavior and shared-device memory."""
import json
import os
import time
from pathlib import Path

import torch
from safetensors.torch import save_file
from transformers import AutoTokenizer
from vllm import LLM, SamplingParams
from vllm.lora.request import LoRARequest

from larb_scaled import server
from probe import mode_ids, prompt_ids, template_parts
from screen import Screen


def export_adapter(state, path):
    path.mkdir(exist_ok=True)
    tensors = {}
    for key, value in state.items():
        module, projection, _ = key.rsplit(".", 2)
        side = {"down": "A", "up": "B"}[projection]
        tensors[f"base_model.model.{module}.lora_{side}.weight"] = value.to(torch.bfloat16).contiguous()
    save_file(tensors, str(path / "adapter_model.safetensors"))
    (path / "adapter_config.json").write_text(json.dumps({
        "peft_type": "LORA", "task_type": "CAUSAL_LM", "r": 16,
        "lora_alpha": 16, "lora_dropout": 0., "target_modules": ["q_proj", "v_proj"],
        "bias": "none",
    }))


def main():
    path = os.environ["LARB_MODEL_PATH"]
    archive = Path(os.environ["ADAPTER_SOURCE"])
    torch.set_num_threads(2)
    tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
    server.TOKENIZER = tok
    contract = server.build_contract("legacy")
    actions = list(mode_ids(tok).values())
    prompts = [{"problem": "What is 17 + 25? Give the integer answer."},
               {"problem": "Find the remainder when 7 to the power 222 is divided by 1000."}]
    ids = [prompt_ids(tok, row["problem"]) for row in prompts]
    states = []
    requests = []
    for index, step in enumerate((8,16), 1):
        state = torch.load(archive / f"adapter-step-{step:02d}.pt", map_location="cpu", weights_only=True)["adapter"]
        states.append(state)
        adapter = Path.cwd() / f"lora-{step}"
        export_adapter(state, adapter)
        requests.append(LoRARequest(f"gate-{step}", index, str(adapter)))
    gpu = torch.cuda.get_device_properties(0)
    gib = gpu.total_memory / 2**30
    ratio = .56 if gib >= 70 else .47
    llm = LLM(model=path, dtype="bfloat16", max_model_len=12288,
        gpu_memory_utilization=ratio, enable_lora=True, max_lora_rank=16, max_loras=1,
        max_cpu_loras=2, enforce_eager=True, enable_prefix_caching=False,
        max_num_seqs=12, max_num_batched_tokens=8192, generation_config="vllm",
        logprobs_mode="processed_logprobs",
        logits_processors=["larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler")
    root = SamplingParams(max_tokens=1, temperature=1., top_p=1., top_k=-1,
                          allowed_token_ids=actions, logprobs=3, seed=317)
    vllm = []
    for adapter in requests:
        out = llm.generate([{"prompt_token_ids": tokens} for tokens in ids], root,
                           lora_request=adapter, use_tqdm=False)
        vllm.append(torch.tensor([[row.outputs[0].logprobs[0][t].logprob for t in actions] for row in out]))
    # Co-residency is deliberately tested with generation idle during backward.
    trainer = Screen(path)
    hf = []
    with torch.no_grad():
        for state in states:
            for name, value in state.items():
                trainer.weights[name].copy_(value)
            hf.append(torch.stack([trainer.route_logits(row).cpu().log_softmax(-1) for row in prompts]))
    observed = [(x-y).abs().max().item() for x,y in zip(vllm,hf)]
    delta = (vllm[1]-vllm[0]).abs().max().item()
    params = []
    cases = []
    for index in range(8):
        row = prompts[index % len(prompts)]
        header, think, _ = template_parts(tok, row["problem"], routed=True)
        if tok.convert_tokens_to_ids("<think>") not in think:
            think += tok.encode("<think>\n", add_special_tokens=False)
        cases.append({"prompt_token_ids":header+[actions[2]]+think})
        key = f"backend--fixed--{index}"
        params.append(SamplingParams(temperature=1., top_p=1., top_k=-1, logprobs=1, seed=702+index,
            max_tokens=1024+len(contract.cue)+contract.answer_cap+2,
            extra_args={"larb": dict(key=key, policy="fixed", budget=1024,
                cue=contract.cue, close_id=contract.close_id, eos_id=contract.eos_id,
                answer_cap=contract.answer_cap, contract=contract.name, arrival_ts=time.monotonic())}))
    start = time.monotonic()
    outputs = llm.generate(cases, params, lora_request=requests[1], use_tqdm=False)
    duration = time.monotonic()-start
    tokens = sum(len(row.outputs[0].token_ids) for row in outputs)
    state_rows = [json.loads((Path(os.environ["LARB_OUT"])/"request-state"/f"backend--fixed--{i}.json").read_text())
                  for i in range(len(outputs))]
    closes = sum(row.outputs[0].token_ids.count(contract.close_id) == 1 for row in outputs)
    capped = sum(row.get("cue_start") == 1024 for row in state_rows)
    response = list(outputs[0].outputs[0].token_ids)
    root_prompt, bridges = trainer.parts(prompts[0])
    bridge = bridges[2]
    forced = list(range(1, 1+len(bridge)))
    cue_start = state_rows[0].get("cue_start")
    if cue_start is not None:
        forced += list(range(1+len(bridge)+cue_start, 1+len(bridge)+cue_start+len(contract.cue)))
    if state_rows[0].get("cap") == "answer_cap":
        forced.append(len(bridge)+len(response))
    trajectory = dict(prompt=root_prompt, response=[actions[2],*bridge,*response],
                      mode=2, masked=forced)
    with torch.no_grad():
        recomputed = trainer.logprobs(trajectory).cpu()[1:]
    observed_tokens = torch.tensor([
        step_logp[token].logprob
        for i, (step_logp, token) in enumerate(zip(outputs[0].outputs[0].logprobs, response))
        if i+1+len(bridge) not in forced
    ])
    errors = (recomputed-observed_tokens).abs()
    assert len(errors) > 0
    start = time.monotonic()
    torch.cuda.reset_peak_memory_stats()
    norm = trainer.step([trajectory], [.5])
    torch.cuda.synchronize()
    result = dict(gpu=gpu.name, memory_gib=gib, vllm_memory_fraction=ratio,
                  max_root_logprob_error=observed, adapter_refresh_delta=delta,
                  training_tokens=len(root_prompt)+1+len(bridge)+len(response),
                  training_seconds=time.monotonic()-start,
                  sampled_logprob_mean_error=float(errors.mean()),
                  sampled_logprob_p95_error=float(errors.quantile(.95)),
                  training_peak_reserved_gib=torch.cuda.max_memory_reserved()/2**30,
                  gradient_norm=norm, output_tokens=tokens, rollout_seconds=duration,
                  output_tokens_per_second=tokens/duration, single_close=closes,
                  cap_bindings=capped, shared_gpu_free_gib=torch.cuda.mem_get_info()[0]/2**30)
    Path("backend-summary.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result), flush=True)
    assert max(observed) <= .15 and delta > .001 and closes == 8 and capped and norm > 0
    assert errors.mean() < .08 and errors.quantile(.95) < .25


if __name__ == "__main__":
    main()
