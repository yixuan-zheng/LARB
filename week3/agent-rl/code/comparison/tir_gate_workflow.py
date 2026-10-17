"""External TIR admission experiment; upstream generation and reward unchanged."""
import asyncio,contextvars,hashlib,time,weakref
from areal import workflow_context
from tools_profile import ToolsWorkflow
from profile_workflow import record
from group_gate import GroupGate
_CONTEXT=contextvars.ContextVar('gate_context')
_GATES=weakref.WeakKeyDictionary()
_GROUP_META={}
def get_gate(phase,kind,capacity):
 loop=asyncio.get_running_loop()
 if loop not in _GATES:_GATES[loop]={}
 key=(phase,kind,capacity)
 if key not in _GATES[loop]:_GATES[loop][key]=GroupGate(capacity,kind,fair_wait=5.)
 return _GATES[loop][key]
class SeededEngine:
 def __init__(self,engine):self.engine=engine
 def __getattr__(self,name):return getattr(self.engine,name)
 async def agenerate(self,req,*args,**kwargs):
  c=_CONTEXT.get();turn=c['request_index'];c['request_index']+=1
  seed=int.from_bytes(hashlib.sha256(f"617:{c['source_id']}:{c['sample_idx']}:{turn}".encode()).digest()[:4],'big')%(2**31)
  req.gconfig=req.gconfig.new(seed=seed)
  return await self.engine.agenerate(req,*args,**kwargs)
class GatedTIRWorkflow(ToolsWorkflow):
 def __init__(self,*args,phase='unset',slot_policy='native',capacity=16,**kwargs):
  super().__init__(*args,**kwargs);self.phase=phase;self.slot_policy=slot_policy;self.capacity=capacity
 async def arun_episode(self,engine,data):
  ctx=workflow_context.get();fields=dict(phase=self.phase,task_id=ctx.task_id,sample_idx=ctx.sample_idx,source_id=data['source_id'])
  _GROUP_META[ctx.task_id]=dict(phase=self.phase,source_id=data['source_id'])
  token=_CONTEXT.set(dict(fields,request_index=0))
  await asyncio.to_thread(record,'gate_episode_start',**fields)
  try:
   result=await super().arun_episode(SeededEngine(engine),data)
   reward=float(result['rewards'].item())
   gate=get_gate(self.phase,self.slot_policy,self.capacity) if self.slot_policy!='native' else None
   if gate:gate.finish_member(ctx.task_id,ctx.sample_idx,reward)
   await asyncio.to_thread(record,'gate_episode_end',reward=reward,gate_stats=dict(gate.stats) if gate else None,**fields)
   return result
  finally:_CONTEXT.reset(token)
 async def _generate_response(self,*args,**kwargs):
  c=_CONTEXT.get();fields=dict(c)
  t=time.perf_counter();queued_at=time.time()
  if self.slot_policy=='native':
   info=dict(wait_seconds=0.,known_mixed=False,reordered=False,queue_depth=0,active=0)
   await asyncio.to_thread(record,'gate_admission',queued_at=queued_at,**info,**fields)
   result=await super()._generate_response(*args,**kwargs)
  else:
   gate=get_gate(self.phase,self.slot_policy,self.capacity)
   async with gate.slot(c['task_id'],c['sample_idx']) as info:
    await asyncio.to_thread(record,'gate_admission',queued_at=queued_at,**info,**fields)
    result=await super()._generate_response(*args,**kwargs)
  await asyncio.to_thread(record,'gate_request_end',seconds=time.perf_counter()-t,**fields)
  return result

def mixed_group(data):
 ctx=workflow_context.get();accepted=bool(0<data['rewards'].mean()<1)
 record('group_filter',task_id=ctx.task_id,accepted=accepted,rows=int(data['rewards'].numel()),**_GROUP_META[ctx.task_id])
 return accepted
