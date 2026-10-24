"""Four policies in one fixed-input, streaming engine for the Step 1 smoke."""
import bootstrap
import json
import os
from pathlib import Path
import time

os.environ.setdefault('VLLM_USE_V1', '1')
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.sampling_params import RequestOutputKind
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.v1.engine.async_llm import AsyncLLM
import uvicorn
from adapter import emit, atomic, read_pressure
from w4_policy import MODES, LONG, arrival_decision

ROOT = Path(os.environ['BURST_OUT'])
MODEL = os.environ['BUDGET_MODEL_PATH']
spec = json.loads((ROOT / 'spec.json').read_text())
protocol = json.loads((ROOT / 'stage3-protocol.json').read_text())
problems = json.loads((ROOT / 'problems100.json').read_text())
tok = AutoTokenizer.from_pretrained(MODEL, local_files_only=True)
cue = tok.encode(protocol['transition_text'], add_special_tokens=False)
close = tok.convert_tokens_to_ids('</think>')
opening = tok.convert_tokens_to_ids('<think>')
eos = tok.convert_tokens_to_ids('<|im_end|>')
prompts = {}
for index in {item['index'] for item in spec['arrivals']}:
    prompt = problems[index]['problem'] + '\nPlease put your final answer within \\boxed{}.'
    rendered = tok.apply_chat_template([dict(role='user', content=prompt)], tokenize=False,
                                      add_generation_prompt=True, enable_thinking=True)
    prompts[index] = (prompt, tok.encode(rendered, add_special_tokens=False))
app = FastAPI()
phase = mode = None
active, seen = set(), set()


@app.get('/health')
async def health():
    return dict(ready=True, phase=phase, active=sorted(active))


@app.post('/phase')
async def set_phase(body: dict):
    global phase, mode
    if active or body['policy'] not in MODES:
        raise HTTPException(409, 'Drain previous phase before changing policy')
    phase, mode = body['phase'], body['policy']
    emit('service', 'phase', phase=phase, policy=mode)
    return dict(phase=phase, policy=mode)


@app.post('/generate')
async def generate(body: dict):
    key, index = body['key'], body['index']
    if phase is None or not key.startswith(phase + '-') or key in seen or index not in prompts:
        raise HTTPException(400, 'Invalid fixed-protocol request')
    seen.add(key)
    active.add(key)
    received = time.monotonic()
    try:
        snapshot = read_pressure()
    except (FileNotFoundError, json.JSONDecodeError):
        snapshot = None
    decision = arrival_decision(mode, snapshot, phase, received,
                                spec['arrival_snapshot_max_age_s'])
    prompt, ids = prompts[index]
    request_mode = mode
    emit('service', 'arrival', key=key, index=index, policy=mode, **decision)
    params = SamplingParams(temperature=0.6, top_p=0.95, top_k=20,
        seed=6222+index, max_tokens=LONG+len(cue)+2048+1,
        skip_special_tokens=False, output_kind=RequestOutputKind.DELTA,
        extra_args={'burst': dict(key=key, policy=mode, budget=decision['budget'], cue=cue,
                                 close_id=close, eos_id=eos, answer_cap=2048)})

    async def stream():
        all_ids, chunks = [], []
        first = None
        terminal = False
        try:
            async for result in engine.generate({'prompt_token_ids': ids}, params, request_id=key):
                output = result.outputs[0]
                all_ids.extend(output.token_ids)
                chunks.append(output.text)
                now = time.monotonic()
                if first is None and output.token_ids:
                    first = now
                    emit('service', 'first_token', key=key, tokens=len(all_ids))
                data = dict(key=key, tokens=len(all_ids), finished=result.finished,
                            monotonic=now, finish_reason=output.finish_reason)
                if result.finished:
                    terminal = True
                    record = dict(**data, index=index, policy=request_mode, received=received,
                        first_token=first, seed=6222+index, arrival_decision=decision,
                        prompt=prompt, prompt_token_ids=ids, token_ids=all_ids,
                        raw_output=''.join(chunks), close_id=close, open_id=opening,
                        eos_id=eos, cue_ids=cue)
                    atomic(ROOT/'requests'/f'{key}.json', record)
                    emit('service', 'completed', key=key, tokens=len(all_ids),
                         finish_reason=output.finish_reason)
                yield json.dumps(data)+'\n'
        finally:
            active.discard(key)
            if not terminal:
                emit('service', 'failed', key=key, reason='stream_without_terminal')
                await engine.abort(key)
    return StreamingResponse(stream(), media_type='application/x-ndjson')


if __name__ == '__main__':
    atomic(ROOT/'pressure.json', dict(step=0, monotonic=time.monotonic(), active=[], waiting=[]))
    args = AsyncEngineArgs(model=MODEL, dtype='bfloat16', max_model_len=24576,
        max_num_seqs=2, max_num_batched_tokens=2048, gpu_memory_utilization=0.80,
        enforce_eager=True, enable_prefix_caching=False, seed=6222,
        logits_processors=['w4_adapter:AdmissionProcessor'],
        scheduler_cls='w4_adapter.AdmissionScheduler', disable_log_stats=True,
        generation_config='vllm')
    engine = AsyncLLM.from_engine_args(args)
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['BUDGET_PORT']), log_level='warning')
