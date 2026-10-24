"""CPU-only Week 4 decisions; model answers never cross this boundary."""
import bootstrap  # noqa: F401
from control import RequestControl, move_rows
from policy import forced_token  # Preserve the Week 3 cue and cap semantics.

MODES = ('full', 'arrival', 'admission', 'live')
LONG = 16384
SHORT = 2048
THRESHOLD = 2


def pressure_budget(waiting):
    return SHORT if waiting >= THRESHOLD else LONG


def arrival_decision(mode, snapshot, phase, now, max_age):
    if mode not in MODES:
        raise ValueError(mode)
    age = None if snapshot is None else now - snapshot['monotonic']
    valid = age is not None and 0 <= age <= max_age
    waiting = [] if snapshot is None else [
        key for key in snapshot['waiting'] if key.startswith(phase + '-')]
    budget = pressure_budget(len(waiting)) if mode == 'arrival' and valid else LONG
    return dict(budget=budget, waiting=waiting, pressure_age_s=age,
                pressure_step=None if snapshot is None else snapshot['step'],
                pressure_valid=valid,
                fallback=mode == 'arrival' and not valid)


def attach_admission(data, snapshot):
    """Mutate only request metadata, before SchedulerOutput leaves schedule().

    Called on NewRequestData.sampling_params.extra_args['burst']. All new
    requests in a step see the same post-schedule queue. A repeated appearance
    retains the first decision, including across chunked prefill/resumption.
    """
    if 'admission' in data:
        return False
    phase = data['key'].rsplit('-', 1)[0]
    waiting = [key for key in snapshot['waiting'] if key.startswith(phase + '-')]
    budget = (pressure_budget(len(waiting))
              if data['policy'] in ('admission', 'live') else data['budget'])
    data['budget'] = budget
    data['admission'] = dict(step=snapshot['step'], waiting=waiting,
                             budget=budget, snapshot_monotonic=snapshot['monotonic'])
    return True


def make_control(data, output):
    if 'admission' not in data:
        raise RuntimeError('Worker received request without scheduler admission decision')
    return RequestControl(key=data['key'], output=output, budget=data['budget'],
                          cue=data['cue'], close_id=data['close_id'],
                          eos_id=data['eos_id'], answer_cap=data['answer_cap'])


def reduce_live(state, mode, waiting):
    state.refresh()
    if (mode == 'live' and waiting >= THRESHOLD and state.budget > SHORT
            and state.output and state.close_index is None and state.force_start is None):
        return state.change(SHORT, state.version + 1)
    return False
