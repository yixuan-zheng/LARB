"""Separately versioned4K/8K pressure rule; no deadline estimator or answer sensing."""
POLICIES=('fixed4k','fixed8k','arrival','entry','live')
SHORT,LONG,THRESHOLD=4096,8192,1

def arrival_budget(policy,waiting,short=SHORT,long=LONG,threshold=THRESHOLD):
    if policy not in POLICIES:raise ValueError(policy)
    if waiting<0 or threshold<1 or not 0<short<long:raise ValueError('Invalid pressure settings')
    return short if policy=='fixed4k' or policy in ('arrival','entry','live') and waiting>=threshold else long

def apply_pressure(state,policy,waiting,short=SHORT,threshold=THRESHOLD):
    state.refresh()
    if policy=='live' and waiting>=threshold and state.budget>short and state.close_index is None and state.force_start is None:
        return state.change(short,state.version+1)
    return False

def forced_token(state):
    # All budgets <=8192: the normal cue starts at its budget, including natural
    # short requests. A live reduction after4096 cues at the current token count.
    return state.next_forced()

def entry_budget(provisional, waiting, generated):
    """Commit once at worker entry, preserving the existing downward-only rule."""
    if generated:
        raise ValueError("First worker admission already has generated tokens")
    return min(provisional, arrival_budget("entry", waiting))
