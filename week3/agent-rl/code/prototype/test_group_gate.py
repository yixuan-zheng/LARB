import asyncio
from group_gate import GroupGate
async def exercise(kind):
 gate=GroupGate(1,kind,fair_wait=10);order=[]
 async with gate.slot('holding',0):
  async def request(group):
   async with gate.slot(group,2):order.append(group)
  a=asyncio.create_task(request('new'));b=asyncio.create_task(request('mixed'));await asyncio.sleep(0)
  gate.finish_member('mixed',0,0);gate.finish_member('mixed',1,1)
 await asyncio.gather(a,b)
 assert gate.active==0 and not gate.queue and gate.stats['max_active']==1
 assert order==(['mixed','new'] if kind=='priority' else ['new','mixed'])
async def cancellation():
 gate=GroupGate(1,'priority')
 async with gate.slot('holding',0):
  async def waiting():
   async with gate.slot('cancel',0):raise AssertionError('cancelled request admitted')
  task=asyncio.create_task(waiting());await asyncio.sleep(0);task.cancel()
  try:await task
  except asyncio.CancelledError:pass
 assert gate.active==0 and not gate.queue
 async with gate.slot('later',0):assert gate.active==1
async def fairness():
 clock=[0.0];gate=GroupGate(1,'priority',fair_wait=5,clock=lambda:clock[0]);order=[]
 async with gate.slot('holding',0):
  async def request(group):
   async with gate.slot(group,2):order.append(group)
  a=asyncio.create_task(request('old'));await asyncio.sleep(0);clock[0]=6
  b=asyncio.create_task(request('mixed'));await asyncio.sleep(0);gate.finish_member('mixed',0,0);gate.finish_member('mixed',1,1)
 await asyncio.gather(a,b);assert order==['old','mixed']
async def main():
 await exercise('fifo');await exercise('priority');await cancellation();await fairness()
 print('PASS: matched capacity, actual priority, starvation promotion, cancellation recovery')
if __name__=='__main__':asyncio.run(main())
