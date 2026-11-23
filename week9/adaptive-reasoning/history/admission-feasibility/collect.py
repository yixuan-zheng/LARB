"""Run the frozen solver on full requests at each assigned cap."""

import asyncio
import random
import time

from math_run import AsyncEngineArgs, AsyncLLM, AutoTokenizer, MODEL, OUT, ROOT, SLOTS
from math_run import config, server, solve

async def main():
    data = config.read_json(ROOT / "freeze.json")
    server.TOKENIZER = AutoTokenizer.from_pretrained(MODEL,local_files_only=True)
    contract = server.build_contract("legacy")
    assert contract.answer_cap == data["answer_cap"]
    engine = AsyncLLM.from_engine_args(AsyncEngineArgs(
        model=MODEL, dtype="bfloat16", max_model_len=12288, max_num_seqs=SLOTS,
        max_num_batched_tokens=8192, gpu_memory_utilization=0.85, enforce_eager=True,
        enable_prefix_caching=False, seed=config.load_protocol()["seeding"]["seed_base"],
        logits_processors=["larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler",
        disable_log_stats=True, generation_config="vllm"))
    try:
        cases = [(row,cap,seed) for row in data["questions"] for cap in data["budgets"]
                 for seed in data["seeds"]]
        random.Random(273).shuffle(cases)
        started = time.monotonic()
        for start in range(0,len(cases),SLOTS):
            wave = cases[start:start+SLOTS]
            result = await asyncio.gather(*(solve(engine,*case,contract,"admission") for case in wave))
            print(f"{start+len(result)}/{len(cases)}",flush=True)
        config.write_json(OUT/"collection.json",dict(cases=len(cases),seconds=time.monotonic()-started))
    finally:
        engine.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
