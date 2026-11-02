"""Deterministic trace recipe; calibration timings only, never correctness labels."""
import hashlib
POLICIES=['fixed4k','fixed8k','live']
def ranked_ids(salt):return sorted(range(1,31),key=lambda i:hashlib.sha256(f'{salt}:{i}'.encode()).hexdigest())
def freeze_trace(spec,calibration):
    # Four8K paired requests from two disjoint pairs. T is deliberately conservative.
    long=[c['latency_seconds'] for c in calibration if c['policy']=='fixed8k']
    if len(calibration)!=8 or len(long)!=4 or min(long)<=0:raise ValueError('Eight complete calibration observations required')
    T=max(long);deadline=spec['deadline_multiplier']*T;ids=ranked_ids(spec['selection_salt'])[:12]
    offsets={'low':[i*1.25*T for i in range(4)],'near':[i*.4*T for i in range(8)],'burst':[0,0]+[.5*T+i*.05 for i in range(6)]+[4*T,5.25*T,6.5*T,7.75*T]}
    conditions=[]
    for j,(name,times) in enumerate(offsets.items()):
        arrivals=[dict(slot=i,id=ids[i],seed=spec['request_seed_base']+ids[i],offset_seconds=t,relative_deadline_seconds=deadline) for i,t in enumerate(times)]
        order=POLICIES[j:]+POLICIES[:j]
        conditions.append(dict(name=name,arrivals=arrivals,policy_order=order,horizon_seconds=max(times)+deadline))
    return dict(scale_seconds=T,source='max observed paired8K calibration latency; no answer labels',conditions=conditions,planned_measured_requests=72,replicates=1,warning='Small development characterization. Calibration does not establish GPU capacity or guarantee low/near load. Observe realized queue occupancy; classify intended loads honestly.')

def validate_trace(spec,trace):
    T=trace['scale_seconds']
    if not isinstance(T,(int,float)) or not 0<T<1800:raise ValueError('Invalid calibration scale')
    dummy=[dict(policy=p,latency_seconds=T) for p in ['fixed4k','fixed8k'] for _ in range(4)]
    if trace!=freeze_trace(spec,dummy):raise ValueError('Trace differs from frozen recipe; version protocol explicitly')
