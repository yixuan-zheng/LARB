"""Time-stepped serving replay for the Week 8 allocation comparison.

Requests arrive, wait in one FIFO queue and hold one of `slots` slots while they
decode. A scored request reaches the 4,096-token checkpoint, where the policy
either forces the answer (short) or lets it think to 8,192 (long). What happens
after the checkpoint is looked up from a recorded Experiment 2 draw, so nothing is
generated. Fillers only load the server: they decode a fixed number of tokens and
are not scored. Prefill is not modeled; a 4K prompt takes one or two engine steps.

This module is imported by the run script. Tests:
    python3 -B week8/allocation/test_sim.py
"""
from collections import namedtuple

SLOTS = 32
CHECKPOINT = 4096
DEADLINE = 240.0

# per-request decode rate (tokens/s) by number of running requests, from the
# scaled-serving P1.3 sweep (week7/scaled-serving/reports/P1-REPORT.md). 1-8 use
# the 4,096-token sweep; 16-32 use the 8,192-token sweep, since these requests
# run past 4K and longer contexts decode more slowly
RATE = {1: 76.7, 2: 71.1, 4: 73.1, 8: 71.2, 16: 65.8, 24: 61.3, 32: 54.7}

# when is 'arrival' or 'checkpoint'; decide(request, waiting) returns 'short' or 'long'
Policy = namedtuple('Policy', 'name when decide')


def rate(running, speed=1.0):
    # linear between measured points, flat outside them
    points = sorted(RATE)
    if running <= points[0]:
        return RATE[points[0]] * speed
    for lo, hi in zip(points, points[1:]):
        if running <= hi:
            f = (running - lo) / (hi - lo)
            return (RATE[lo] + f * (RATE[hi] - RATE[lo])) * speed
    return RATE[points[-1]] * speed


def fixed(arm):
    return Policy(f'fixed-{arm}', 'checkpoint', lambda req, waiting: arm)


def arrival_rule(threshold):
    # decide once at arrival: short if `threshold` or more are already waiting
    return Policy('arrival', 'arrival',
                  lambda req, waiting: 'short' if waiting >= threshold else 'long')


def value_rule(name, value, lam, slots=SLOTS):
    # extend while the request's value beats the price of holding a slot,
    # which grows with the share of the server's slots that have someone waiting
    return Policy(name, 'checkpoint',
                  lambda req, waiting: 'long' if value(req) > lam * waiting / slots else 'short')


def simulate(requests, policy, slots=SLOTS, speed=1.0, lag=0.0, step=1.0):
    """Replay one trace under one policy and return one result per request.

    speed scales every decode rate. lag makes decisions see the queue as it was
    `lag` seconds earlier, the admission-timing error check. Deadlines always
    count from the true arrival.
    """
    pending = sorted(requests, key=lambda r: r['arrival'])
    queue, running, results, history = [], [], [], []
    t, i = 0.0, 0

    def seen():
        # waiting count at the last step at or before t - lag
        return history[max(0, min(len(history) - 1, int((t - lag) / step)))] if history else 0

    def admit():
        while queue and len(running) < slots:
            state = queue.pop(0)
            state['start'] = t
            running.append(state)

    while i < len(pending) or queue or running:
        while i < len(pending) and pending[i]['arrival'] <= t:
            req = pending[i]
            state = dict(req=req, generated=0.0, arm=None, waiting_seen=None, start=None)
            if req.get('checkpoint') is None:
                state['total'] = req['tokens']
            else:
                state['total'] = None
                if policy.when == 'arrival':
                    state['waiting_seen'] = len(queue) if lag == 0 else seen()
                    state['arm'] = policy.decide(req, state['waiting_seen'])
            queue.append(state)
            admit()
            i += 1
        admit()
        history.append(len(queue))

        if running:
            r = rate(len(running), speed)
            finished = []
            for state in running:
                req = state['req']
                state['generated'] += r * step
                if state['total'] is None and state['generated'] >= req['checkpoint']:
                    if state['arm'] is None:
                        state['waiting_seen'] = seen()
                        state['arm'] = policy.decide(req, state['waiting_seen'])
                    state['total'] = req['checkpoint'] + req[state['arm']][0]
                if state['total'] is not None and state['generated'] >= state['total']:
                    # interpolate the finish inside the step
                    state['finish'] = t + step - (state['generated'] - state['total']) / r
                    finished.append(state)
            for state in finished:
                running.remove(state)
                results.append(result(state))
        t += step
    return results


def result(state):
    req = state['req']
    latency = state['finish'] - req['arrival']
    scored = req.get('checkpoint') is not None
    correct = req[state['arm']][1] if scored else 0
    on_time = latency <= req.get('deadline', DEADLINE)
    return dict(key=req['key'], prefix=req.get('prefix'), scored=scored, arm=state['arm'],
                arrival=req['arrival'], start=state['start'], finish=state['finish'],
                latency=latency, waiting_seen=state['waiting_seen'], tokens=state['total'],
                correct=correct, on_time=int(on_time), good=int(bool(correct) and on_time))


def summarize(results, minutes):
    # minutes is the trace span, the same for every policy, so goodput differences
    # are differences in good answers
    scored = [r for r in results if r['scored']]
    good = sum(r['good'] for r in scored)
    return dict(requests=len(scored), good=good, correct=sum(r['correct'] for r in scored),
                on_time=sum(r['on_time'] for r in scored),
                extended=sum(r['arm'] == 'long' for r in scored),
                tokens=sum(r['tokens'] for r in scored),
                goodput_per_min=good / minutes)
