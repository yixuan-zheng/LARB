"""Offline calibration/replay checks with the real trace-freezing function."""
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('BURST_OUT','/tmp/not-a-model-run')
os.environ.setdefault('BUDGET_PORT','12345')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from run_comparison import freeze_trace

spec=json.loads((Path(__file__).resolve().parents[1]/'spec.json').read_text())
cal=dict(client=[dict(status='terminal',scheduled=100,client_finished=110),
                 dict(status='terminal',scheduled=100,client_finished=120)])
trace=freeze_trace(spec,cal)
assert trace['burst_at_seconds']==2.5
assert trace['relative_deadline_seconds']==40
assert abs(trace['observation_horizon_seconds']-42.95)<1e-9
assert [r['index'] for r in trace['arrivals']]==list(range(12))
assert [r['offset_seconds'] for r in trace['arrivals'][:2]]==[0,0]
assert spec['policy_orders'][1]==list(reversed(spec['policy_orders'][0]))
for clients in [[],[dict(status='error')],[dict(status='error'),dict(status='terminal')]]:
    try:
        freeze_trace(spec,dict(client=clients))
    except RuntimeError:
        continue
    raise AssertionError('Invalid calibration accepted')
print('PASS: real calibration rule, fixed indices/horizon, reverse order, and rejection of incomplete calibration')
