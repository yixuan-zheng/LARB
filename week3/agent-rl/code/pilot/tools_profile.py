"""Measurement-only subclass; upstream TIR generation/tool/reward semantics unchanged."""
import copy,hashlib,time,contextvars
_EP=contextvars.ContextVar("tir_measurement")
from tir_workflow import TIRWorkflow
from areal.engine.vllm_remote import VLLMBackend
# Upstream TIR detects tool delimiters in returned tokens. Its original SGLang
# backend keeps them; vLLM needs this explicit existing API option.
_original_request=VLLMBackend.build_generation_request
def _retain_delimiters(self,req,*args,**kwargs):
 request=_original_request(self,req,*args,**kwargs)
 if req.gconfig.stop:request.payload["include_stop_str_in_output"]=True
 return request
VLLMBackend.build_generation_request=_retain_delimiters
from profile_workflow import record
from areal import workflow_context
class ToolsWorkflow(TIRWorkflow):
 async def arun_episode(self,engine,data):
  ctx=workflow_context.get();fields=dict(task_id=ctx.task_id,sample_idx=ctx.sample_idx,is_eval=ctx.is_eval,prompt_sha256=hashlib.sha256(data['messages'][0]['content'].encode()).hexdigest())
  _EP.set(dict(fields=fields,turns=[],tools=[]));start=time.perf_counter();record('workflow_start',version=engine.get_version(),**fields)
  try:
   result=await super().arun_episode(engine,copy.deepcopy(data))
   record('workflow_end',seconds=time.perf_counter()-start,reward=float(result['rewards'].item()),loss_tokens=int(result['loss_mask'].sum().item()),sequence_tokens=int(result['input_ids'].numel()),retained_version_min=int(result['versions'][result['loss_mask'].bool()].min().item()) if result['loss_mask'].any() else None,turns=_EP.get()['turns'],tools=_EP.get()['tools'],end_version=engine.get_version(),**_EP.get()['fields'])
   return result
  except BaseException as e:
   record('workflow_error',seconds=time.perf_counter()-start,error=repr(e),turns=_EP.get()['turns'],tools=_EP.get()['tools'],end_version=engine.get_version(),**_EP.get()['fields']);raise
 async def _generate_response(self,*args,**kwargs):
  start=time.perf_counter();resp,stop=await super()._generate_response(*args,**kwargs)
  row=dict(seconds=time.perf_counter()-start,input_tokens=len(resp.input_tokens),output_tokens=len(resp.output_tokens),version_min=min(resp.output_versions) if resp.output_versions else None,version_max=max(resp.output_versions) if resp.output_versions else None,stop_reason=stop,response=self.tokenizer.decode(resp.output_tokens))
  _EP.get()['turns'].append(row);record('generation_end',**row,**_EP.get()['fields'])
  return resp,stop
 async def _execute_tools(self,*args,**kwargs):
  start=time.perf_counter();result,status=await super()._execute_tools(*args,**kwargs)
  row=dict(seconds=time.perf_counter()-start,request=str(args[0]) if args else str(kwargs),result=str(result),status=str(status));_EP.get()['tools'].append(row);record('tool_end',**row,**_EP.get()['fields'])
  return result,status
