"""Loopback-only streaming service around the real vLLM async engine."""
import asyncio
import json
import os
from pathlib import Path
import time

os.environ.setdefault('VLLM_USE_V1', '1')
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.v1.engine.async_llm import AsyncLLM
import uvicorn
from live_budget import emit

ROOT = Path(os.environ['BUDGET_PROOF_DIR'])
MODEL = os.environ['BUDGET_MODEL_PATH']
protocol = json.loads((ROOT / 'protocol.json').read_text())
tok = AutoTokenizer.from_pretrained(MODEL)
cue = tok.encode(protocol['transition_text'], add_special_tokens=False)
close = tok.convert_tokens_to_ids('</think>')
eos = tok.convert_tokens_to_ids('<|im_end|>')
args = AsyncEngineArgs(model=MODEL, dtype='bfloat16', max_model_len=24576,
    max_num_seqs=2, max_num_batched_tokens=2048, gpu_memory_utilization=0.80,
    enforce_eager=True, enable_prefix_caching=False,
    logits_processors=['live_budget:LiveBudgetProcessor'],
    scheduler_cls='live_budget.AuditScheduler', disable_log_stats=True,
    generation_config='vllm', seed=6222)
app = FastAPI()
seen = set()
commands = {}


@app.get('/health')
async def health():
    return {'ready': True, 'vllm': '0.11.2', 'max_num_seqs': 2}


@app.post('/budget/{key}')
async def budget(key: str, body: dict):
    if key not in seen or not isinstance(body.get('budget'), int) or body['budget'] < 1:
        raise HTTPException(400, 'Known request and positive integer budget required')
    version = commands.get(key, {}).get('version', 0) + 1
    commands[key] = dict(budget=body['budget'], version=version)
    temp = ROOT / 'control.tmp'
    temp.write_text(json.dumps(commands))
    temp.replace(ROOT / 'control.json')
    emit('service', 'budget_written', key=key, **commands[key])
    return commands[key]


@app.post('/generate')
async def generate(body: dict):
    key = body['key']
    if key in seen:
        raise HTTPException(409, 'Request identity cannot be reused')
    seen.add(key)
    rendered = tok.apply_chat_template([dict(role='user', content=body['prompt'])],
        tokenize=False, add_generation_prompt=True, enable_thinking=True)
    params = SamplingParams(temperature=0.6, top_p=0.95, top_k=20,
        seed=6222 + body['index'], max_tokens=16384 + len(cue) + 2048 + 1,
        skip_special_tokens=False,
        extra_args={'live_budget': dict(key=key, budget=16384, cue=cue,
                                       close_id=close, eos_id=eos, answer_cap=2048)})
    emit('service', 'submitted', key=key, index=body['index'])

    async def stream():
        async for result in engine.generate(rendered, params, request_id=key):
            output = result.outputs[0]
            data = dict(key=key, token_ids=list(output.token_ids), text=output.text,
                        finished=result.finished, finish_reason=output.finish_reason,
                        monotonic=time.monotonic())
            if result.finished:
                (ROOT / f'{key}.json').write_text(json.dumps(data, indent=2) + '\n')
                emit('service', 'completed', key=key, tokens=len(output.token_ids),
                     finish_reason=output.finish_reason)
            yield json.dumps(data) + '\n'
    return StreamingResponse(stream(), media_type='application/x-ndjson')


if __name__ == '__main__':
    (ROOT / 'control.json').write_text('{}\n')
    engine = AsyncLLM.from_engine_args(args)
    uvicorn.run(app, host='127.0.0.1', port=int(os.environ['BUDGET_PORT']), log_level='warning')
