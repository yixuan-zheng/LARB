import asyncio
import json
import os
import random
import statistics
import sys
import threading
import time
from pathlib import Path

ROOT = Path(os.environ["STAGE_B_ROOT"])
OUT = Path(os.environ["LARB_OUT"])
SLOTS = int(os.environ["LARB_MAX_NUM_SEQS"])
MODEL = os.environ["LARB_MODEL_PATH"]
sys.path.insert(0, str(ROOT / "repo/week7/scaled-serving/code/tools"))

from larb_scaled import analysis, config, grading, server
from throughput_sweep import gpu_sampler, one_request
from math_timeout import generate_with_timeout

from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.sampling_params import StructuredOutputsParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.v1.engine.async_llm import AsyncLLM

async def generate(engine, ids, params, key):
    start = time.monotonic()
    first = None
    async for result in engine.generate({"prompt_token_ids": ids}, params, request_id=key):
        if first is None:
            first = time.monotonic()
    output = result.outputs[0]
    return dict(token_ids=list(output.token_ids), raw_output=output.text, complete=result.finished,
                seconds=time.monotonic()-start, ttft=first-start, prompt_tokens=len(ids))

async def solve(engine, row, budget, seed, contract, mode):
    key = f"{mode}--fixed{budget}--{row['question_id']}--{seed}"
    params = SamplingParams(max_tokens=budget + len(contract.cue) + contract.answer_cap + 2,
        temperature=0.6, top_p=0.95, top_k=20, seed=seed, skip_special_tokens=False,
        extra_args={"larb": dict(key=key, policy="fixed", budget=budget,
            cue=contract.cue, close_id=contract.close_id, eos_id=contract.eos_id,
            answer_cap=contract.answer_cap, contract=contract.name, arrival_ts=time.monotonic())})
    raw = await generate(engine, row["solver_ids"], params, key)
    state = await server.read_request_state(key)
    if not state:
        raise RuntimeError(f"missing controller state: {key}")
    raw.update(close_id=contract.close_id, eos_id=contract.eos_id, cue_ids=contract.cue,
               answer_cap=contract.answer_cap, capped=state.get("cap"))
    cue_start = state.get("cue_start")
    if cue_start is not None and cue_start != budget:
        raise ValueError(f"cue position {cue_start} differs from budget {budget}")
    audit = analysis.audit_completion(raw, cue_start)
    grade = grading.grade(raw["raw_output"], row["answer"], use_math_verify=False)
    raw.update(mode=mode, seed=seed, budget=budget, question_id=row["question_id"],
               correct=bool(audit["normal"] and grade["correct"]), audit=audit,
               preemptions=state["preemptions"], grade=grade, output_tokens=len(raw["token_ids"]))
    config.write_json(OUT / "solves" / f"{key}.json", raw)
    return raw

async def select(engine, row, budgets, mode="selector"):
    key = f"{mode}--{row['question_id']}"
    params = SamplingParams(max_tokens=8, temperature=0,
                            structured_outputs=StructuredOutputsParams(choice=list(budgets)))
    raw = await generate_with_timeout(engine, key, generate(engine, row["selector_ids"], params, key))
    if raw is None:
        raw = dict(seconds=30.0, prompt_tokens=len(row["selector_ids"]), token_ids=[], raw_output="")
        label, status = "", "timeout"
    else:
        label = raw["raw_output"].strip()
        status = "ok" if label in budgets else "invalid"
    raw.update(question_id=row["question_id"], label=label, status=status,
               budget=budgets.get(label, 4096), output_tokens=len(raw["token_ids"]))
    config.write_json(OUT / mode / f"{row['question_id']}.json", raw)
    return raw

async def timed_probe(engine, rows, contract, mode):
    start = time.monotonic()
    fixed = await asyncio.gather(*(solve(engine, row, 8192, 17, contract, mode) for row in rows))
    return dict(seconds=time.monotonic()-start, tokens=sum(r["output_tokens"] for r in fixed),
        preemptions=sum(r["preemptions"] for r in fixed), reasons=[r["audit"]["reason"] for r in fixed])

async def run(gpu):
    manifest = config.read_json(ROOT / "freeze.json")
    budgets = manifest["budgets"]
    server.TOKENIZER = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
    contract = server.build_contract("legacy")
    model_config = config.read_json(Path(MODEL) / "config.json")
    assert [model_config[k] for k in ("num_hidden_layers", "num_key_value_heads", "head_dim")] == [36, 8, 128]
    protocol = config.load_protocol()
    probe_start = time.monotonic()
    engine = AsyncLLM.from_engine_args(AsyncEngineArgs(
        model=MODEL, dtype="bfloat16", max_model_len=12288, max_num_seqs=SLOTS,
        max_num_batched_tokens=8192, gpu_memory_utilization=0.85, enforce_eager=True,
        enable_prefix_caching=False, seed=protocol["seeding"]["seed_base"],
        logits_processors=["larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler",
        disable_log_stats=True, generation_config="vllm"))
    try:
        mode = sys.argv[1]
        if mode == "probe":
            rows = sorted(manifest["calibration"], key=lambda row: -row["prompt_tokens"])
            fixed = await timed_probe(engine, rows[:SLOTS], contract, "probe")
            if fixed["preemptions"] or any(reason not in {"normal", "answer_cap"} for reason in fixed["reasons"]):
                raise RuntimeError(f"unstable probe: {fixed}")
            # Exercise long simultaneous contexts through the existing capacity probe, including full decode.
            longest = rows[0]["solver_ids"]
            tokens = min(10240, 12288-len(longest))
            started = time.monotonic()
            measured = await asyncio.gather(*(one_request(
                engine, SamplingParams, longest, tokens, "capacity", 201 + i) for i in range(SLOTS)))
            elapsed = time.monotonic() - started
            summary = dict(slots=SLOTS, solver_probe=fixed, capacity_tokens_per_request=tokens,
                capacity_output_tokens_per_second=sum(r["tokens"] for r in measured) / elapsed,
                capacity_seconds=elapsed, peak_memory_mib=max((r["memory_mib"] for r in gpu), default=None),
                probe_total_seconds=time.monotonic()-probe_start)
            config.write_json(OUT / "probe.json", summary)
            print(json.dumps(summary), flush=True)
            return
        assert mode == "smoke"
        rows = manifest["smoke"]
        randomizer = random.Random(273)
        cases = [(row, budget, seed) for row in rows for budget in budgets.values()
                 for seed in manifest["seeds"]]
        randomizer.shuffle(cases)
        started = time.monotonic()
        for start in range(0, len(cases), SLOTS):
            wave = cases[start:start+SLOTS]
            wave_start = time.monotonic()
            results = await asyncio.gather(*(solve(engine, *case, contract, "smoke") for case in wave))
            config.write_json(OUT / "waves" / f"{start:03}.json",
                dict(seconds=time.monotonic()-wave_start, tokens=sum(r["output_tokens"] for r in results)))
            print(f"smoke {start+len(wave)}/{len(cases)}", flush=True)
        config.write_json(OUT / "smoke.json", dict(slots=SLOTS, cases=len(cases),
                                                  seconds=time.monotonic()-started))
        for row in rows[:3]:
            check = await select(engine, row, budgets, "preflight")
            if check["status"] != "ok":
                print("Constrained-choice preflight failed; fixed grid is complete.", flush=True)
                return
        for row in rows:
            await select(engine, row, budgets)
        calibration = manifest["calibration"]
        inflight = [asyncio.create_task(solve(engine, row, 8192, 29, contract, "mixed"))
                    for row in calibration[:SLOTS]]
        await asyncio.sleep(1)
        await select(engine, calibration[-1], budgets, "loaded-selector")
        await asyncio.gather(*inflight)
    finally:
        engine.shutdown()

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stop = threading.Event()
    gpu = []
    thread = threading.Thread(target=gpu_sampler, args=(stop, gpu), daemon=True)
    thread.start()
    try:
        asyncio.run(run(gpu))
    finally:
        stop.set()
        thread.join(timeout=5)
        config.write_json(OUT / "gpu.json", gpu)

if __name__ == "__main__":
    main()
