"""Frozen-plan trace construction and accounting; CPU-only."""
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def cohort_positions(plan, count):
    """Block 0 uses the cohort in published rank order; block 1 rotates it."""
    ids = plan['cohort_rank_order'][:count]
    rotate = plan['block_rotation']
    return [ids, ids[rotate:] + ids[:rotate]]


def offsets_for(plan, condition, count, unit, burst):
    if condition == 'gate':
        return list(plan['gate']['offsets_seconds'])
    if condition == 'one_at_a_time':
        return [2 * unit * i for i in range(count)]
    if condition == 'constant_pressure':
        return [.3 * unit * i for i in range(count)]
    if condition == 'slack_rush_recovery':
        slow = max(1, count // 3)
        fast = max(1, count // 3)
        first = [2 * unit * i for i in range(slow)]
        start = 2 * unit * (slow - 1) + unit
        rushing = [start + burst + .05 * i for i in range(fast)]
        resuming = [start + burst + 4 * unit + 2 * unit * i for i in range(count - slow - fast)]
        return first + rushing + resuming
    raise ValueError('Unknown condition')


def trace_for(plan, condition, calibration, frozen_monotonic):
    rows = calibration['client']
    if len(rows) != 2 or any(r['status'] != 'terminal' for r in rows):
        raise ValueError('Calibration requires two normal terminal responses')
    durations = [r['client_finished'] - r['scheduled'] for r in rows]
    if any(d <= 0 for d in durations):
        raise ValueError('Invalid calibration clock')
    unit = max(30., max(durations))
    burst = .25 * min(durations)
    if condition == 'gate':
        indices = list(plan['gate']['indices'])
        offsets = offsets_for(plan, condition, len(indices), unit, burst)
        positions = [indices]
        block_order = [0]
        orders = {0: list(plan['gate']['policies'])}
    else:
        count = plan['coverage']['questions']
        positions = cohort_positions(plan, count)
        offsets = offsets_for(plan, condition, count, unit, burst)
        block_order = [0, 1]
        orders = {block: list(order) for block, order in enumerate(plan['orders'])}
    arrivals = [[dict(index=index, offset_seconds=float(offset))
                 for index, offset in zip(ids, offsets)] for ids in positions]
    return dict(condition=condition, arrivals_by_block=arrivals, block_order=block_order,
                orders=orders, relative_deadline_seconds=2 * unit,
                observation_horizon_seconds=max(offsets) + 2 * unit,
                calibration_latencies_seconds=durations, unit_seconds=unit,
                burst_at_seconds=burst, frozen_monotonic=frozen_monotonic,
                clock_domain='client.monotonic')


def source_path(repo, legacy, name):
    return legacy / name.removeprefix('week3/larb/') if name.startswith('week3/larb/') else repo / name
