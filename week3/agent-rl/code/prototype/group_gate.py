"""Bounded completion admission; preserve all requests and grouped outcomes."""
import asyncio,time
from dataclasses import dataclass
from contextlib import asynccontextmanager
@dataclass
class Pending:
 group: object
 member: object
 queued: float
 order: int
 future: asyncio.Future
class GroupGate:
 def __init__(self,capacity,kind='fifo',fair_wait=5.0,clock=time.monotonic):
  if capacity<1 or kind not in ['fifo','priority']:raise ValueError('invalid gate')
  self.capacity=capacity;self.kind=kind;self.fair_wait=fair_wait;self.clock=clock
  self.active=0;self.queue=[];self.counter=0;self.rewards={};self.started={};self.stats={'admissions':0,'reordered':0,'informative_admissions':0,'max_active':0}
 def informative(self,group):
  outcomes=list(self.rewards.get(group,{}).values())
  return any(r>0 for r in outcomes) and any(r<1 for r in outcomes)
 def finish_member(self,group,member,reward):
  self.rewards.setdefault(group,{})[member]=float(reward)
  self._dispatch()
 def _key(self,p):
  if self.kind=='fifo':return (0,p.order)
  if self.clock()-p.queued>=self.fair_wait:return (0,p.order)
  if self.informative(p.group):return (1,self.started[p.group],p.order)
  return (2,p.order)
 def _dispatch(self):
  while self.active<self.capacity and self.queue:
   p=min(self.queue,key=self._key);first=min(self.queue,key=lambda x:x.order);self.queue.remove(p)
   if p.future.cancelled():continue
   self.active+=1;self.stats['admissions']+=1;self.stats['max_active']=max(self.stats['max_active'],self.active)
   self.stats['reordered']+=int(p is not first);self.stats['informative_admissions']+=int(self.informative(p.group))
   p.future.set_result({'wait_seconds':self.clock()-p.queued,'known_mixed':self.informative(p.group),'reordered':p is not first,'queue_depth':len(self.queue),'active':self.active})
 @asynccontextmanager
 async def slot(self,group,member):
  self.started.setdefault(group,self.clock());loop=asyncio.get_running_loop();future=loop.create_future();self.counter+=1
  p=Pending(group,member,self.clock(),self.counter,future);self.queue.append(p);self._dispatch()
  granted=False
  try:
   info=await future;granted=True;yield info
  finally:
   # Cancellation can arrive after granting but before await resumes.
   was_granted=granted or (future.done() and not future.cancelled())
   if p in self.queue:self.queue.remove(p)
   if was_granted:self.active-=1
   self._dispatch()
