"""Run the forced-mode development grid using LARB's reasoning controller."""
import asyncio
import itertools
import json
import os
import random
import time
from pathlib import Path

from larb_scaled import analysis, config, datasets, grading, server

MODES = {"Low": ("1", 0), "Medium": ("2", 2048), "High": ("3", 8192)}
NOTICE = "\nChoose effort with one digit first: 1 = direct answer, 2 = brief reasoning, 3 = extended reasoning. Then solve."
SLOTS = 8


def mode_ids(tokenizer):
    ids = {name: tokenizer.encode(label, add_special_tokens=False) for name, (label, _) in MODES.items()}
    assert all(len(tokens) == 1 for tokens in ids.values())
    assert len({tokens[0] for tokens in ids.values()}) == len(MODES)
    return {name: tokens[0] for name, tokens in ids.items()}


def template_parts(tokenizer, problem, *, routed):
    message = [{"role": "user", "content": datasets.prompt_for(problem) + (NOTICE if routed else "")}]
    def render(thinking):
        return tokenizer.apply_chat_template(message, tokenize=True,
            add_generation_prompt=True, enable_thinking=thinking)
    thinking, direct = render(True), render(False)
    opening = tokenizer.convert_tokens_to_ids("<think>")
    closing = tokenizer.convert_tokens_to_ids("</think>")
    # The pinned template may leave the thinking opener to the model.
    # Split at the native assistant header, before any thinking delimiters.
    header = tokenizer.encode("<|im_start|>assistant\n", add_special_tokens=False)
    end = max(i + len(header) for i in range(len(thinking)) if thinking[i:i+len(header)] == header)
    assert thinking[:end] == direct[:end]
    assert opening in direct[end:] and closing in direct[end:]
    return thinking[:end], thinking[end:], direct[end:]


def prompt_ids(tokenizer, problem):
    return template_parts(tokenizer, problem, routed=True)[0]


async def run():
    from transformers import AutoTokenizer
    from vllm import SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.v1.engine.async_llm import AsyncLLM

    root = Path.cwd()
    model = os.environ["LARB_MODEL_PATH"]
    server.TOKENIZER = tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    token_ids = mode_ids(tokenizer)
    legacy = server.build_contract("legacy")
    close = legacy.close_id
    fixture = os.environ.get("LARB_MODE_FIXTURE") == "1"
    if fixture:
        rows = [dict(question_id="fixture-easy", stratum="easy", problem="What is 17 + 25? Give the integer answer.", answer="42"),
                dict(question_id="fixture-harder", stratum="harder",
                     problem="Find the remainder when 7 to the power 222 is divided by 1000.", answer="49")]
        rows[1]["answer"] = str(pow(7, 222, 1000))
    else:
        rows = json.loads((root / "freeze.json").read_text())
    binding = os.environ.get("LARB_BINDING_FIXTURE") == "1"
    arms = (*MODES, "NativeThink", "NativeDirect") if fixture else tuple(MODES)
    if binding:
        assert fixture
        rows = rows[:1]
        arms = ("Medium", "High")
    cases = list(itertools.product(rows, arms, (17,) if fixture else (17, 29)))
    random.Random(273).shuffle(cases)
    start = time.monotonic()
    engine = AsyncLLM.from_engine_args(AsyncEngineArgs(
        model=model, dtype="bfloat16", max_model_len=12288, max_num_seqs=SLOTS,
        max_num_batched_tokens=8192, gpu_memory_utilization=.85, enforce_eager=True,
        enable_prefix_caching=False, generation_config="vllm",
        logits_processors=["binding_processor:BindingProcessor" if binding else
                           "larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler", disable_log_stats=True,
    ))

    async def solve(row, mode, seed):
        started = time.monotonic()
        key = f"stage1--fixed--{row['question_id']}--{mode}--{seed}"
        routed = mode in MODES
        label = token_ids.get(mode)
        cap = MODES[mode][1] if routed else 8192
        direct = mode in ("Low", "NativeDirect")
        prompt, thinking_prefix, direct_prefix = template_parts(tokenizer, row["problem"], routed=routed)
        opening = tokenizer.convert_tokens_to_ids("<think>")
        bridge = direct_prefix if direct else thinking_prefix
        if routed and not direct and opening not in bridge:
            bridge = [*bridge, *tokenizer.encode("<think>\n", add_special_tokens=False)]
        header = prompt + ([label] if routed else []) + bridge
        params = SamplingParams(
            temperature=0, seed=seed, skip_special_tokens=False,
            max_tokens=(legacy.answer_cap if direct else cap + len(legacy.cue) + legacy.answer_cap),
            extra_args=({"larb": dict(key=key, policy="fixed", budget=cap,
                cue=legacy.cue, close_id=close, eos_id=legacy.eos_id,
                answer_cap=legacy.answer_cap, contract="legacy", arrival_ts=started)}
                if routed and not direct else None),
        )
        async for result in engine.generate({"prompt_token_ids": header}, params, request_id=key):
            pass
        result_ids = list(result.outputs[0].token_ids)
        state = await server.read_request_state(key) if routed and not direct else {}
        if routed and not direct and not state:
            raise RuntimeError(f"Missing controller state for {key}")
        cue_start = state.get("cue_start")
        if cue_start is not None and cue_start != cap:
            raise RuntimeError(f"Wrong cue position for {key}: {cue_start}")
        audit_ids = [close, *result_ids] if direct else result_ids
        audit = analysis.audit_completion(dict(token_ids=audit_ids, close_id=close,
            eos_id=legacy.eos_id, cue_ids=legacy.cue, answer_cap=legacy.answer_cap,
            complete=result.finished, capped=state.get("cap")), cue_start)
        first_close = audit_ids.index(close) if close in audit_ids else None
        answer_ids = audit_ids[first_close + 1:] if first_close is not None else []
        answer = tokenizer.decode(answer_ids, skip_special_tokens=True)
        grade = grading.grade(answer, row["answer"], use_math_verify=False)
        leaked = any(token in answer_ids for token in (close, opening))
        forced = list(range(len(bridge)))
        if cue_start is not None:
            offset = len(bridge) + cue_start
            forced.extend(range(offset, offset + len(legacy.cue)))
        if state.get("cap") == "answer_cap":
            forced.append(len(bridge) + len(result_ids)-1)
        record = dict(key=key, question_id=row["question_id"], stratum=row["stratum"], mode=mode, seed=seed,
            correct=bool(audit["normal"] and grade["correct"] and not leaked),
            audit=audit, leaked=leaked, answer=answer, prompt=prompt, label=label,
            output=bridge + result_ids if routed else result_ids, generated_tokens=len(result_ids),
            forced_positions=forced, bridge_tokens=len(bridge), cue_tokens=len(legacy.cue),
            binding_fixture=binding, seconds=time.monotonic()-started,
            preemptions=state.get("preemptions", 0))
        config.write_json(root / "solves" / f"{key}.json", record)
        return record

    try:
        started = time.monotonic()
        print(json.dumps({"startup_seconds": started-start, "mode_ids": token_ids}), flush=True)
        results = []
        for offset in range(0, len(cases), SLOTS):
            results.extend(await asyncio.gather(*(solve(row, mode, seed) for row, mode, seed in cases[offset:offset+SLOTS])))
            print(f"Forced rollouts {len(results)}/{len(cases)}", flush=True)
        elapsed = time.monotonic()-started
        config.write_json(root / "rollout-summary.json", dict(seconds=elapsed,
            generated_tokens=sum(r["generated_tokens"] + (1 if r["label"] is not None else 0) for r in results),
            modes={mode: dict(n=len(group), correct=sum(r["correct"] for r in group),
                reasoning_tokens=sum(r["audit"]["thinking_tokens"] for r in group),
                answer_tokens=sum(r["audit"]["answer_tokens"] for r in group),
                forced_closures=sum(r["audit"]["forced"] for r in group),
                failures={reason: sum(r["audit"]["reason"] == reason for r in group)
                          for reason in sorted({r["audit"]["reason"] for r in group})},
                leakage=sum(r["leaked"] for r in group))
                for mode in arms for group in [[r for r in results if r["mode"] == mode]]}))
        if binding:
            for row in results:
                assert row["correct"] and row["audit"]["forced"], row["key"]
                assert row["audit"]["thinking_tokens"] == MODES[row["mode"]][1], row["key"]
    finally:
        engine.shutdown()


if __name__ == "__main__":
    asyncio.run(run())
