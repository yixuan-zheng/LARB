"""Local vLLM service for the scaled rig.

Run on the GPU node as a module:
    LARB_OUT=... LARB_PORT=18761 python -m larb_scaled.server

The module imports vLLM only inside main()/route construction so the CPU tests
and readiness checker can import the rest of the package without torch.
"""
import asyncio
import json
import os
import time
import traceback
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from transformers import AutoTokenizer

from larb_scaled import config
from larb_scaled.bus import BUS, atomic, emit, read_snapshot
from larb_scaled.contract import Contract
from larb_scaled.policy import admission_budget, pressure_threshold

PROTOCOL = config.load_protocol()
QUESTIONS = {}
TOKENIZER = None
CONTRACT = None
SAMPLING_PARAMS = None
PHASE = None
ARM = None
CONDITION = None
ACTIVE = set()
SEEN = set()
APP = FastAPI()
OUT = Path(os.environ.get("LARB_OUT", "."))


def load_questions():
    global QUESTIONS
    QUESTIONS = {}
    with (config.DATA_DIR / "processed/questions.jsonl").open() as handle:
        for line in handle:
            if line.strip():
                row = json.loads(line)
                QUESTIONS[row["question_id"]] = row


def build_contract(name):
    cfg = PROTOCOL["answer_contracts"][name]
    cue = TOKENIZER.encode(cfg["cue"], add_special_tokens=False)
    close_id = TOKENIZER.convert_tokens_to_ids("</think>")
    eos_id = TOKENIZER.convert_tokens_to_ids("<|im_end|>")
    closing_brace = TOKENIZER.convert_tokens_to_ids("}")
    if closing_brace is None or closing_brace < 0:
        closing_brace = TOKENIZER.encode("}", add_special_tokens=False)[-1]
    answer_cap = int(os.environ.get("LARB_FORCE_ANSWER_CAP") or cfg["answer_cap"])
    contract = Contract(name=name, cue=list(cue), close_id=close_id, eos_id=eos_id,
                        answer_cap=answer_cap,
                        closing_brace_id=closing_brace if name == "short_boxed" else None,
                        force_closing_brace=bool(cfg.get("force_closing_brace", False)),
                        cue_text=cfg["cue"])
    contract.validate()
    return contract


def render_prompt(question):
    rendered = TOKENIZER.apply_chat_template(
        [{"role": "user", "content": question["prompt"]}],
        tokenize=False, add_generation_prompt=True, enable_thinking=True)
    ids = TOKENIZER.encode(rendered, add_special_tokens=False)
    return rendered, ids


def _threshold(max_num_seqs):
    explicit = int(os.environ.get("LARB_THRESHOLD", "0"))
    if explicit:
        return explicit
    pressure = PROTOCOL["policy"]["pressure"]
    return pressure_threshold(max_num_seqs, pressure["threshold_fraction"],
                              pressure["threshold_minimum"])


def _queue_snapshot():
    """Latest queue snapshot, preferring the in-process bus.

    When vLLM runs the engine core in a separate process, the in-process bus
    of the HTTP frontend never updates; fall back to the file the scheduler
    writes at a fixed stride.
    """
    snapshot = BUS.get()
    if time.monotonic() - float(snapshot.get("monotonic", 0.0)) > 0.5:
        snapshot = read_snapshot() or snapshot
    return snapshot


async def read_request_state(key, timeout=3.0):
    """Read the controller state the engine-core process persisted for `key`.

    The final event write can trail the last streamed token by a scheduler
    step, so retry briefly. An empty dict means the controller never saw the
    request (recorded as a failure, not imputed).
    """
    path = OUT / "request-state" / f"{key}.json"
    deadline = time.monotonic() + timeout
    while True:
        try:
            return json.loads(path.read_text())
        except (OSError, json.JSONDecodeError):
            if time.monotonic() >= deadline:
                return {}
            await asyncio.sleep(0.02)


@APP.get("/health")
async def health():
    return dict(ready=True, phase=PHASE, arm=ARM, active=sorted(ACTIVE))


@APP.post("/phase")
async def set_phase(body: dict):
    global PHASE, ARM, CONDITION
    if ACTIVE:
        raise HTTPException(409, "Drain before changing phase")
    if body.get("arm") not in PROTOCOL["policy"]["arms"]:
        raise HTTPException(400, "Unknown arm")
    PHASE = body["phase"]
    ARM = body["arm"]
    CONDITION = body.get("condition", PHASE.split("-")[0])
    emit("service", "phase", phase=PHASE, arm=ARM, condition=CONDITION)
    return dict(phase=PHASE, arm=ARM, condition=CONDITION)


@APP.post("/generate")
async def generate(body: dict):
    key = body.get("key")
    if PHASE is None or ARM is None:
        raise HTTPException(409, "No active phase")
    if not key or not key.startswith(f"{CONDITION}--{ARM}--"):
        raise HTTPException(400, "Request key does not match the active phase")
    if key in SEEN or key in ACTIVE:
        raise HTTPException(409, "Duplicate or already active request")
    question_id = body.get("question_id")
    question = QUESTIONS.get(question_id)
    if question is None:
        raise HTTPException(400, "Unknown question")
    request_class = body.get("class", "signal")
    if request_class not in ("signal", "filler"):
        raise HTTPException(400, "Unknown request class")
    seed = int(body["seed"])
    max_num_seqs = int(os.environ.get("LARB_MAX_NUM_SEQS", PROTOCOL["engine"]["max_num_seqs"]))
    threshold = _threshold(max_num_seqs)
    snapshot = _queue_snapshot()
    waiting = [k for k in snapshot.get("waiting", []) if k.startswith(f"{CONDITION}--")]
    if request_class == "filler":
        budget = int(body.get("initial_budget") or PROTOCOL["workload"]["filler_budget"])
    else:
        # Gate-only override: forces a cue at a known position to prove the
        # controller's exact-cue contract. Unexpensive and unused by P2.
        budget = (int(os.environ.get("LARB_FORCE_BUDGET") or 0)
                  or admission_budget(ARM, len(waiting), threshold))
    rendered, prompt_ids = render_prompt(question)
    max_tokens = (PROTOCOL["budgets"]["long"] if request_class == "signal" else budget) + \
        len(CONTRACT.cue) + CONTRACT.answer_cap + 2
    if len(prompt_ids) + max_tokens > PROTOCOL["engine"]["max_model_len"]:
        raise HTTPException(400, "Prompt exceeds the frozen context")
    extra = dict(
        key=key, policy=ARM, budget=budget, cue=list(CONTRACT.cue),
        close_id=CONTRACT.close_id, eos_id=CONTRACT.eos_id,
        answer_cap=CONTRACT.answer_cap, closing_brace_id=CONTRACT.closing_brace_id,
        force_closing_brace=CONTRACT.force_closing_brace, contract=CONTRACT.name,
        arrival_ts=time.monotonic(),
    )
    params = SAMPLING_PARAMS(
        temperature=PROTOCOL["engine"]["sampling"]["temperature"],
        top_p=PROTOCOL["engine"]["sampling"]["top_p"],
        top_k=PROTOCOL["engine"]["sampling"]["top_k"],
        seed=seed, max_tokens=max_tokens, skip_special_tokens=False,
        extra_args={"larb": extra},
    )
    active_key = key
    ACTIVE.add(active_key)
    SEEN.add(active_key)
    received = time.monotonic()
    engine = APP.state.engine

    async def stream():
        token_ids = []
        text = ""
        first_token = None
        finished = None
        error = None
        complete = False
        try:
            async for result in engine.generate({"prompt_token_ids": prompt_ids}, params,
                                                request_id=key):
                output = result.outputs[0]
                token_ids = list(output.token_ids)
                text = output.text
                now = time.monotonic()
                first_token = now if first_token is None else first_token
                finished = now
                if result.finished:
                    complete = True
                    break
        except BaseException as exc:
            error = repr(exc)
            emit("service", "request_error", key=key, error=error,
                 traceback=traceback.format_exc())
        finally:
            state = BUS.state(key)
            persisted = await read_request_state(key)
            if persisted:
                cuts = persisted.get("cuts") or []
                cue = {"tokens": persisted.get("cue_start"),
                       "monotonic": persisted.get("cue_time")}
                scheduler_start = (persisted.get("scheduler_start")
                                   or state["scheduler_start"])
                capped = persisted.get("cap") or state["cap"]
                preemptions = persisted.get("preemptions", state["preemptions"])
                final_budget = persisted.get("budget", budget)
            else:
                cuts = state["cuts"]
                cue = state["cue"] or {}
                scheduler_start = state["scheduler_start"]
                capped = state["cap"]
                preemptions = state["preemptions"]
                final_budget = cuts[-1]["budget"] if cuts else budget
            record = dict(
                key=key, trace_id=body.get("trace_id"), phase=PHASE, condition=CONDITION,
                arm=ARM, policy=ARM, **{"class": request_class}, question_id=question_id,
                seed=seed, scored=bool(body.get("scored", request_class == "signal")),
                received=received, scheduled=body.get("scheduled"),
                scheduler_start=scheduler_start, first_token=first_token,
                finished=finished, complete=complete, error=error,
                initial_budget=budget, final_budget=final_budget,
                waiting_at_arrival=len(waiting), pressure_threshold=threshold,
                pressure_fraction=(len(waiting) / max_num_seqs if max_num_seqs else None),
                pressure_at_arrival=bool(len(waiting) >= threshold),
                capped=capped, max_num_seqs=max_num_seqs,
                deadline_s=body.get("deadline_s"), prompt=rendered,
                prompt_token_ids=prompt_ids, raw_output=text, token_ids=token_ids,
                cue_ids=list(CONTRACT.cue), close_id=CONTRACT.close_id,
                eos_id=CONTRACT.eos_id, answer_cap=CONTRACT.answer_cap,
                closing_brace_id=CONTRACT.closing_brace_id, contract=CONTRACT.name,
                cue_start=cue.get("tokens"), cue_start_time=cue.get("monotonic"),
                cut_events=cuts, preemptions=preemptions,
                reference=question["answer"], source=question["pool"],
                exposure=question["exposure"], answer_type=question["answer_type"],
            )
            atomic(OUT / "requests" / f"{key}.json", record)
            ACTIVE.discard(active_key)
            emit("service", "completed", key=key, complete=complete, error=error,
                 tokens=len(token_ids), cuts=len(cuts))
        yield json.dumps(dict(key=key, finished=complete, monotonic=finished,
                              tokens=len(token_ids))) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


def main():
    global TOKENIZER, CONTRACT, SAMPLING_PARAMS
    from vllm import SamplingParams
    from vllm.engine.arg_utils import AsyncEngineArgs
    from vllm.v1.engine.async_llm import AsyncLLM
    import uvicorn

    model = os.environ.get("LARB_MODEL_PATH", PROTOCOL["model"]["local_path_default"])
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "requests").mkdir(parents=True, exist_ok=True)
    TOKENIZER = AutoTokenizer.from_pretrained(model, local_files_only=True)
    load_questions()
    CONTRACT = build_contract(os.environ.get("LARB_CONTRACT", "legacy"))
    SAMPLING_PARAMS = SamplingParams
    atomic(OUT / "server-config.json", dict(
        model=model, contract=CONTRACT.name, cue=CONTRACT.cue,
        close_id=CONTRACT.close_id, eos_id=CONTRACT.eos_id,
        answer_cap=CONTRACT.answer_cap, closing_brace_id=CONTRACT.closing_brace_id,
        max_num_seqs=int(os.environ.get("LARB_MAX_NUM_SEQS", PROTOCOL["engine"]["max_num_seqs"])),
    ))
    args = AsyncEngineArgs(
        model=model, dtype=PROTOCOL["model"]["dtype"],
        max_model_len=PROTOCOL["engine"]["max_model_len"],
        max_num_seqs=int(os.environ.get("LARB_MAX_NUM_SEQS", PROTOCOL["engine"]["max_num_seqs"])),
        max_num_batched_tokens=PROTOCOL["engine"]["max_num_batched_tokens"],
        gpu_memory_utilization=float(os.environ.get("LARB_GPU_UTIL",
                                                     PROTOCOL["engine"]["gpu_memory_utilization"])),
        enforce_eager=bool(int(os.environ.get("LARB_ENFORCE_EAGER", "0"))),
        enable_prefix_caching=False,
        seed=PROTOCOL["seeding"]["seed_base"],
        logits_processors=["larb_scaled.controller:PressureProcessor"],
        scheduler_cls="larb_scaled.controller.QueueAuditScheduler",
        disable_log_stats=True,
        generation_config="vllm",
    )
    APP.state.engine = AsyncLLM.from_engine_args(args)
    uvicorn.run(APP, host="127.0.0.1", port=int(os.environ.get("LARB_PORT", "18761")),
                log_level="warning")


if __name__ == "__main__":
    main()

