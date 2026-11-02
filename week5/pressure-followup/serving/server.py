"""One local asynchronous vLLM service; policy changes only when fully drained."""
import json,os,time
from pathlib import Path
from fastapi import FastAPI,HTTPException
from fastapi.responses import StreamingResponse
from transformers import AutoTokenizer
from vllm import SamplingParams
from vllm.sampling_params import RequestOutputKind
from vllm.engine.arg_utils import AsyncEngineArgs
from vllm.v1.engine.async_llm import AsyncLLM
import uvicorn
from pressure_adapter import emit,atomic,read_pressure
from queue_policy import POLICIES,arrival_budget
ROOT=Path(os.environ['BURST_OUT']);HERE=Path(__file__).resolve().parent
spec=json.loads((HERE/'spec.json').read_text());model=os.environ['BUDGET_MODEL_PATH']
problems={q['id']:q for q in json.loads((HERE.parent/'screen/inputs/problems.json').read_text())}
tok=AutoTokenizer.from_pretrained(model,local_files_only=True)
cue=tok.encode(spec['transition_text'],add_special_tokens=False);close=tok.convert_tokens_to_ids('</think>');eos=tok.convert_tokens_to_ids('<|im_end|>')
app=FastAPI();phase=None;policy=None;active=set();seen=set()
@app.get('/health')
async def health():return dict(ready=True,phase=phase,active=sorted(active))
@app.post('/phase')
async def set_phase(body:dict):
 global phase,policy
 if active or body['policy'] not in POLICIES:raise HTTPException(409,'Drain before policy change')
 phase=body['phase'];policy=body['policy'];emit('service','phase',phase=phase,policy=policy);return dict(phase=phase)
@app.post('/generate')
async def generate(body:dict):
 key=body['key'];qid=body['id'];seed=body['seed']
 if phase is None or not key.startswith(phase+'--') or key in seen or qid not in problems:raise HTTPException(400,'Invalid frozen request')
 seen.add(key);active.add(key);received=time.monotonic();snap=read_pressure();waiting=[k for k in snap['waiting'] if k.startswith(phase+'--')];budget=arrival_budget(policy,len(waiting));mode=policy
 text=problems[qid]['problem']+'\nPlease put your final answer within \\boxed{}.'
 rendered=tok.apply_chat_template([dict(role='user',content=text)],tokenize=False,add_generation_prompt=True,enable_thinking=True);prompt_ids=tok.encode(rendered,add_special_tokens=False)
 if len(prompt_ids)+8192+len(cue)+2048+1>24576:active.remove(key);raise HTTPException(400,'Prompt exceeds frozen context')
 params=SamplingParams(temperature=.6,top_p=.95,top_k=20,seed=seed,max_tokens=8192+len(cue)+2048+1,skip_special_tokens=False,output_kind=RequestOutputKind.DELTA,extra_args={'burst':dict(key=key,policy=mode,budget=budget,cue=cue,close_id=close,eos_id=eos,answer_cap=2048)})
 async def stream():
  ids=[];chunks=[];first=None;finished=False;error=None;last=None
  try:
   async for result in engine.generate({'prompt_token_ids':prompt_ids},params,request_id=key):
    output=result.outputs[0];ids.extend(output.token_ids);chunks.append(output.text);now=time.monotonic();first=now if first is None else first;last=now;finished=result.finished
    if finished:break
   if not finished:raise RuntimeError('Engine ended without terminal record')
  except BaseException as exc:
   error=repr(exc);raise
  finally:
   record=dict(key=key,id=qid,seed=seed,policy=mode,received=received,first_token=first,finished=last,complete=finished,error=error,initial_budget=budget,waiting_at_arrival=waiting,pressure_step=snap['step'],pressure_age_ms=1000*(received-snap['monotonic']),prompt=rendered,prompt_token_ids=prompt_ids,raw_output=''.join(chunks),token_ids=ids,cue_ids=cue,close_id=close,eos_id=eos,reference=problems[qid]['answer'])
   atomic(ROOT/'requests'/(key+'.json'),record);active.discard(key);emit('service','completed',key=key,complete=finished,error=error)
  yield json.dumps(dict(key=key,finished=finished,monotonic=last,tokens=len(ids)))+'\n'
 return StreamingResponse(stream(),media_type='application/x-ndjson')
if __name__=='__main__':
 atomic(ROOT/'pressure.json',dict(step=0,monotonic=time.monotonic(),active=[],waiting=[]))
 args=AsyncEngineArgs(model=model,dtype='bfloat16',max_model_len=24576,max_num_seqs=2,max_num_batched_tokens=2048,gpu_memory_utilization=.8,enforce_eager=True,enable_prefix_caching=False,seed=6222,logits_processors=['pressure_adapter:PressureProcessor'],scheduler_cls='pressure_adapter.QueueAuditScheduler',disable_log_stats=True,generation_config='vllm')
 engine=AsyncLLM.from_engine_args(args);uvicorn.run(app,host='127.0.0.1',port=int(os.environ['BUDGET_PORT']),log_level='warning')
