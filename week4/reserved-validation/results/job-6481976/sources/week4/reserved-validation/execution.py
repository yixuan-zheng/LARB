"""Frozen-plan trace construction and accounting; CPU-only."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def trace_for(plan, shard, condition, calibration, frozen_monotonic):
    rows=calibration['client']
    if len(rows)!=2 or any(r['status']!='terminal' for r in rows):
        raise ValueError('Calibration requires two normal terminal responses')
    durations=[r['client_finished']-r['scheduled'] for r in rows]
    if any(d<=0 for d in durations):raise ValueError('Invalid calibration clock')
    unit=max(30.,max(durations));burst=.25*min(durations)
    if condition=='low_load':offsets=[2*unit*i for i in range(12)]
    elif condition=='late_burst':offsets=[0.,0.]+[burst+.05*i for i in range(10)]
    elif condition=='sustained_pressure':offsets=[.3*unit*i for i in range(12)]
    else:raise ValueError('Unknown condition')
    cohort=plan['sample']['shards'][shard]
    arrivals=[[dict(index=index,offset_seconds=offset) for index,offset in zip(ids,offsets)]
              for ids in cohort['block_positions']]
    return dict(shard=shard,condition=condition,arrivals_by_block=arrivals,
        relative_deadline_seconds=2*unit,observation_horizon_seconds=max(offsets)+2*unit,
        calibration_latencies_seconds=durations,unit_seconds=unit,burst_at_seconds=burst,
        orders=plan['orders'],frozen_monotonic=frozen_monotonic,clock_domain='client.monotonic')


def source_path(repo,legacy,name):
    return legacy/name.removeprefix('week3/larb/') if name.startswith('week3/larb/') else repo/name
