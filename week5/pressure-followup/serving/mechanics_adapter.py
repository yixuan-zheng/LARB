"""Synthetic-only live-engine boundary gate. Never use for scientific requests."""
from pressure_adapter import PressureProcessor,emit
from queue_policy import apply_pressure
class MechanicsProcessor(PressureProcessor):
 def update_state(self,batch_update):
  super().update_state(batch_update)
  for state in self.rows.values():
   if state.key not in ('mechanics-below--r0','mechanics-late--r0'):raise RuntimeError('Synthetic gate keys only')
   trigger=64 if 'below' in state.key else 5000
   if len(state.output)>=trigger and apply_pressure(state,'live',1):emit('worker','synthetic_gate_cut',key=state.key,tokens=len(state.output),budget=state.budget)
 def apply(self,logits):
  super().apply(logits)
  for row,state in self.rows.items():
   # Artificially keep thinking open until the tested boundary, only in this gate.
   hold=4096 if 'below' in state.key else 5000
   if len(state.output)<hold:logits[row,state.close_id]=float('-inf');logits[row,state.eos_id]=float('-inf')
  return logits
