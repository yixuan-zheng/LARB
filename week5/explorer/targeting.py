"""Lane C shadow rule: which running request to cut so a waiting one makes its deadline.

CPU-only and pure: it only returns decisions, never changes a budget. The same
functions are used for the offline replay of saved records.

A running request is a dict(key, tokens, budget, closed, cued):
  tokens  thinking tokens generated so far
  closed  model already wrote </think> on its own
  cued    the forced transition cue has started
A waiter is a dict(key, deadline), in queue (FIFO) order.
est holds tau (s/token), answer (s from cue to finished answer),
service (s for a waiter once admitted) and remaining(t) (expected extra
thinking tokens for a request that has already thought t).
"""
SHORT = 2048


def eligible(r):
    return r['tokens'] > 0 and not r['closed'] and not r['cued'] and r['budget'] > SHORT


def free_time(r, est, cut=False):
    """Seconds until this request gives up its slot."""
    if r['closed'] or r['cued']:
        return est['answer']
    budget = SHORT if cut else r['budget']
    left = min(max(0, budget - r['tokens']), est['remaining'](r['tokens']))
    return left * est['tau'] + est['answer']


def on_time(now, running, waiters, est, cut=None):
    """Which of the first two waiters finish by their deadline if `cut` is cut now."""
    # stock fifo: the head waiter takes the first slot to free up, the next one the second
    slots = sorted(free_time(r, est, r['key'] == cut) for r in running)
    return [now + slot + est['service'] <= w['deadline'] for slot, w in zip(slots, waiters)]


def shadow_decision(now, running, waiters, est):
    """Cut at most one request, and only if that gets more waiters in on time."""
    if not waiters:
        return dict(cut=None, reason='no_waiter')
    base = on_time(now, running, waiters, est)
    choices = [r for r in running if eligible(r)]
    if not choices:
        return dict(cut=None, reason='nothing_eligible', base=base)
    gains = {}
    for r in choices:
        gains[r['key']] = sum(on_time(now, running, waiters, est, r['key'])) - sum(base)
    best = max(gains.values())
    if best <= 0:
        return dict(cut=None, reason='fine' if all(base) else 'doomed', base=base)
    winners = [r for r in choices if gains[r['key']] == best]
    pick = min(winners, key=lambda r: free_time(r, est, cut=True))
    return dict(cut=pick['key'], reason='rescue', base=base, gain=best)


def cut_all_decision(running, waiters, threshold=1):
    """'Cut whenever full' (live_one): cut every eligible request once enough wait."""
    if len(waiters) < threshold:
        return []
    return [r['key'] for r in running if eligible(r)]


def category(shadow, baseline):
    """How the shadow rule's choice differs from cut-whenever-full at one decision point."""
    mine = [shadow['cut']] if shadow['cut'] else []
    if sorted(mine) == sorted(baseline):
        return 'agree'
    if not mine:
        return shadow['reason']
    if len(baseline) > 1:
        return 'one_of_two'
    return 'other'
