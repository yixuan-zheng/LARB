"""Pure policy/control logic for the frozen burst pilot."""
from control import RequestControl


def arrival_budget(policy, waiting, short=2048):
    return short if policy in ('arrival', 'live') and waiting >= 2 else 16384


def apply_pressure(state, policy, waiting, short=2048):
    if (policy == 'live' and waiting >= 2 and state.budget > short
            and state.close_index is None and state.force_start is None):
        return state.change(short, state.version + 1)
    return False


def forced_token(state):
    state.refresh()
    if state.close_index is None and state.force_start is None and len(state.output) >= 16384:
        return state.eos_id, 'thinking_cap'
    token = state.next_forced()
    reason = 'answer_cap' if token == state.eos_id else None
    return token, reason
