"""CPU-only Week 5 decisions: selectable waiting threshold for the cut trigger.

The Week 3/4 controller is imported and never modified: this module reuses the
unchanged RequestControl state machine and the Week 3 forced-cue semantics, and
only makes the pressure threshold a per-policy choice so that the existing
two-waiter rule and the Week 5 one-waiter candidate can run in the same engine.
Model answers never cross this boundary.
"""
import bootstrap  # noqa: F401
from control import RequestControl, move_rows  # unchanged Week 3 state machine
from policy import forced_token  # unchanged Week 3 cue and cap semantics

LONG = 16384
SHORT = 2048
FIXED = {'fixed2048': 2048, 'fixed4096': 4096}
# Minimum number of waiting requests that switches a policy to the short budget.
# 'live' is Week 4 behaviour exactly (two waiters). 'live_one' is the Week 5
# candidate: the same rule at one waiter, applied at admission and to running
# requests. 'full' thinks without load reaction and is used only for the shared
# calibration/gate requests, never as a measured policy.
TRIGGERS = {'live': 2, 'live_one': 1}
LIVE_MODES = ('live', 'live_one')
MODES = ('full',) + tuple(FIXED) + tuple(TRIGGERS)
MEASURED = ('fixed2048', 'fixed4096', 'live', 'live_one')


def trigger_threshold(mode):
    if mode not in MODES:
        raise ValueError(mode)
    return TRIGGERS.get(mode)


def pressure_budget(mode, waiting):
    threshold = trigger_threshold(mode)
    if threshold is None:
        raise ValueError('No load trigger for ' + mode)
    return SHORT if waiting >= threshold else LONG


def arrival_decision(mode, snapshot, phase, now, max_age):
    """Client-side log only; the scheduler decision below is authoritative."""
    if mode not in MODES:
        raise ValueError(mode)
    age = None if snapshot is None else now - snapshot['monotonic']
    valid = age is not None and 0 <= age <= max_age
    waiting = [] if snapshot is None else [
        key for key in snapshot['waiting'] if key.startswith(phase + '-')]
    budget = (FIXED[mode] if mode in FIXED else
              pressure_budget(mode, len(waiting)) if mode in TRIGGERS and valid else LONG)
    return dict(budget=budget, waiting=waiting, pressure_age_s=age,
                pressure_step=None if snapshot is None else snapshot['step'],
                pressure_valid=valid, trigger=trigger_threshold(mode),
                fallback=mode in TRIGGERS and not valid)


def attach_admission(data, snapshot):
    """Mutate only request metadata, before SchedulerOutput leaves schedule().

    Called on NewRequestData.sampling_params.extra_args['burst']. All new
    requests in a step see the same post-schedule queue. A repeated appearance
    retains the first decision, including across chunked prefill/resumption.
    """
    if 'admission' in data:
        return False
    mode = data['policy']
    phase = data['key'].rsplit('-', 1)[0]
    waiting = [key for key in snapshot['waiting'] if key.startswith(phase + '-')]
    budget = (FIXED[mode] if mode in FIXED else
              pressure_budget(mode, len(waiting)) if mode in TRIGGERS else data['budget'])
    data['budget'] = budget
    data['admission'] = dict(step=snapshot['step'], waiting=waiting, budget=budget,
                             trigger=trigger_threshold(mode),
                             snapshot_monotonic=snapshot['monotonic'])
    return True


def make_control(data, output):
    if 'admission' not in data:
        raise RuntimeError('Worker received request without scheduler admission decision')
    return RequestControl(key=data['key'], output=output, budget=data['budget'],
                          cue=data['cue'], close_id=data['close_id'],
                          eos_id=data['eos_id'], answer_cap=data['answer_cap'])


def reduce_live(state, mode, waiting):
    """Week 4's live rule with the threshold taken from the policy, not a constant."""
    state.refresh()
    threshold = trigger_threshold(mode)
    if (mode in LIVE_MODES and waiting >= threshold and state.budget > SHORT
            and state.output and state.close_index is None and state.force_start is None):
        return state.change(SHORT, state.version + 1)
    return False
