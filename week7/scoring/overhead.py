"""Charge each measured reader for its own reading, then compare it with two
question-only controls: the archived week 6 forecast (Q), and the same reader
given only the question (protocol rule 1).

Run from the repository root after build_sheet.py:
    python3 -B week7/scoring/overhead.py

Each reader is scored with its own ranking and its own measured token use. Costs
are in served-token equivalents: one decode token of the served model (Qwen3-4B)
counts as 1. A reader prefill token counts as PREFILL_WEIGHT; the default of 1
is a conservative upper bound we have not measured. Each reader's scale converts
its tokens into served tokens by parameter count, a rough proxy for compute.

Both controls are charged nothing. Each is one call per question, made in
advance, so this favors the controls and makes any reader win conservative.

Latency is charged separately as stalled slot time. While the reader runs, the
request either waits in its slot or keeps decoding tokens that are thrown away
if it is not extended, so the cost is at most reader seconds x SLOT_RATE.
The token curves below stay compute-only; the stall charge is printed next to them.
"""
from frontier import cheapest_for, best_within, load_rows, sweep

PREFILL_WEIGHT = 1.0
# every accuracy target above forcing all answers (20 correct) up to all-long (28)
TARGETS = range(21, 29)
# per-slot decode rate on the serving rig: 2,129.7 tok/s at 32 slots, 4,096+128 tokens
# (scaled-serving/reports/P1-REPORT.md, gate P1.3)
SLOT_RATE = 2129.7 / 32
CONSERVATIVE_HEADROOM = 124  # bootstrap 2.5% on the week 6 cohort, bootstrap-summary.json

# name: (score column, input column, output column, scale, same-reader question-only column, seconds column)
READERS = {
    'bounded 512-token reader (4-bit qwen3-4b)': ('b_score', 'b_in', 'b_out', 1.0, 'bq_score', 'b_sec'),
    'full-prefix reader (qwen3.8-27b)': ('f_score', 'f_in', 'f_out', 27 / 4, 'fq_score', 'f_sec'),
}


def reader_cost(rows, reader, weight=PREFILL_WEIGHT):
    _, inp, out, scale, _, _ = READERS[reader]
    return scale * sum(weight * r[inp] + r[out] for r in rows) / len(rows)


def stall_cost(rows, reader):
    # served tokens the request's slot could have decoded while the reader ran
    sec = READERS[reader][5]
    return SLOT_RATE * sum(r[sec] for r in rows) / len(rows)


def charged(points, per_prefix, n_prefixes):
    # a reader has to read every prefix before it can rank them, not just the extended ones
    return [dict(p, tokens=p['tokens'] + per_prefix * n_prefixes) for p in points]


def headroom(q, r, n_prefixes):
    # most a reader can pay per prefix and still match Q, per accuracy target
    return {t: (cheapest_for(q, t) - cheapest_for(r, t)) / n_prefixes for t in TARGETS}


def main():
    rows = load_rows()
    n = len(rows)
    q = sweep(rows, 'q_score')

    p_room = headroom(q, sweep(rows, 'p_score'), n)
    print('reference: week 6 full-prefix ai readers (best ranking, reading cost never measured)')
    print(f'   free headroom per prefix: {min(p_room.values()):,.0f} to {max(p_room.values()):,.0f}')
    print(f'   as stall time at {SLOT_RATE:.1f} tok/s per slot: at most {max(p_room.values()) / SLOT_RATE:.1f} s'
          f' per prefix; the conservative {CONSERVATIVE_HEADROOM} tokens is {CONSERVATIVE_HEADROOM / SLOT_RATE:.1f} s\n')

    for name, (score, inp, out, scale, control, sec) in READERS.items():
        curve = sweep(rows, score)
        room = headroom(q, curve, n)
        cost = reader_cost(rows, name)
        paid = charged(curve, cost, n)
        q28, r28 = cheapest_for(q, 28), cheapest_for(paid, 28)
        fit = best_within(paid, q[28]['tokens'])
        mean_in = sum(r[inp] for r in rows) / n
        mean_out = sum(r[out] for r in rows) / n

        print(name)
        print(f'   measured per prefix: {mean_in:,.0f} in + {mean_out:,.0f} out, x{scale:.2f} scale'
              f' -> {cost:,.0f} served-token equivalents')
        secs = sorted(r[sec] for r in rows)
        stall = stall_cost(rows, name)
        print(f'   measured wall time per prefix: {sum(secs) / n:.1f} s mean, {secs[int(0.9 * n) - 1]:.1f} s p90'
              ' (not on the serving gpu)')
        print(f'   stall charge if the request waits: {stall:,.0f}; compute + stall = {cost + stall:,.0f}'
              f' ({(cost + stall) / CONSERVATIVE_HEADROOM:,.0f}x the conservative headroom)')
        print(f'   correct at 28 extensions (reading free): {curve[28]["correct"]:.1f}   (Q {q[28]["correct"]:.1f})')
        print('   free headroom per prefix by target: '
              + ', '.join(f'{t}:{h:,.0f}' for t, h in room.items()))
        print(f'   to reach 28 correct, paying the reader: Q {q28:,.0f}   reader {r28:,.0f}'
              f'   reader saves {q28 - r28:+,.0f}')
        print(f'   at Q\'s 28-extension cost ({q[28]["tokens"]:,.0f}): Q {q[28]["correct"]:.1f}   reader '
              + (f'{fit:.1f}' if fit is not None else 'cannot fit (reading alone exceeds budget)'))
        if max(room.values()) <= 0:
            print('   no free headroom: even with zero reading cost it never beats Q on tokens')
        else:
            # prefill weight at which this reader just breaks even at its best target
            best = max(room.values())
            limit = (best / scale - mean_out) / mean_in
            if limit <= 0:
                print('   cannot break even at any prefill cost: its output tokens alone exceed the headroom')
            else:
                print(f'   breaks even at its best target only if a prefill token costs <= {limit:.2f}'
                      ' decode tokens')

        # rule 1: does seeing the trajectory help this reader, or is it just a better reader?
        c = sweep(rows, control)
        c28, budget = cheapest_for(c, 28), c[28]['tokens']
        own_fit = best_within(paid, budget)
        own_room = headroom(c, curve, n)
        print('   vs the same reader on the question only (control charged nothing):')
        print(f'      correct at 28 extensions (reading free): {curve[28]["correct"]:.1f}'
              f'   (control {c[28]["correct"]:.1f})')
        print('      free headroom per prefix by target: '
              + ', '.join(f'{t}:{h:,.0f}' for t, h in own_room.items()))
        print(f'      to reach 28 correct, paying the reader: control {c28:,.0f}   reader {r28:,.0f}'
              f'   reader saves {c28 - r28:+,.0f}')
        print(f'      at the control\'s 28-extension cost ({budget:,.0f}): control {c[28]["correct"]:.1f}   reader '
              + (f'{own_fit:.1f}' if own_fit is not None else 'cannot fit (reading alone exceeds budget)'))
        print()


if __name__ == '__main__':
    main()
