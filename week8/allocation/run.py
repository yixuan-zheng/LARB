"""Build the allocation replay workload and calibrate it without looking at outcomes.

Run from the repository root after build_draws.py:
    python3 -B week8/allocation/run.py calibrate   # timing only -> calibration.json

Every arrival in a scaled-serving trace becomes one Experiment 2 checkpoint
request. Prefixes are dealt in shuffled rounds so each appears about equally,
and each request gets one random short draw and one random long draw. The same
requests are replayed under every policy, so policy differences are paired.
Calibration loads the draws without grades: it sees token counts only.
"""
import argparse
import csv
import hashlib
import json
import random
import re
from collections import defaultdict
from pathlib import Path

from sim import CHECKPOINT, DEADLINE, SLOTS, arrival_rule, fixed, simulate, value_rule

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DRAWS = HERE / 'draws.csv'
VALUES = ROOT / 'week7/continuation-sampling/results/full-summary.json'  # until the frozen export lands
TRACES = ROOT / 'week7/scaled-serving/artifacts/traces'
CALIBRATION = HERE / 'calibration.json'

SEED = 8222
RATES = range(100, 1001, 20)  # requests per hour
TARGET_MISS = 0.25     # fixed 8K misses about a quarter of deadlines, inside the 15-40% band
ANCHOR = 1             # the constant rule extends only while fewer than 1 wait
SHUFFLES = 50          # shuffled-value controls checked during calibration
ARRIVAL_THRESHOLD = 8  # p1 pressure threshold: 8 waiting for 32 slots


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_draws(grades):
    # prefix -> arm -> replicate -> (suffix tokens, correct); correct is None when blind
    draws = defaultdict(lambda: defaultdict(dict))
    with open(DRAWS) as f:
        for row in csv.DictReader(f):
            correct = int(row['correct']) if grades else None
            draws[row['prefix']][row['arm']][int(row['replicate'])] = (int(row['suffix_tokens']), correct)
    return draws


def load_values():
    # own: the prefix's p8 - p4. other: the same question's other prefix, so a
    # request is never ranked by the draws that also decide its outcome
    own = {key: row['delta'] for key, row in json.loads(VALUES.read_text())['prefixes'].items()}
    other = {}
    for key in own:
        question, block = re.fullmatch(r'(q\d+)-b([01])', key).groups()
        other[key] = own[f'{question}-b{1 - int(block)}']
    constant = sum(own.values()) / len(own)
    return dict(own=own, other=other, constant=constant)


def load_trace(name):
    path = TRACES / f'{name}.jsonl'
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return sorted(rows, key=lambda r: r['arrival_s']), path


def build_workload(draws, rows, rate, seed=SEED):
    """Rescale a trace to `rate` requests per hour and fill it with checkpoint requests.

    The random draws do not depend on the rate, so two rates replay the same
    requests on a different clock.
    """
    rng = random.Random(seed)
    prefixes = sorted(draws)
    order = []
    while len(order) < len(rows):
        block = prefixes[:]
        rng.shuffle(block)
        order += block
    scale = len(rows) * 3600 / rows[-1]['arrival_s'] / rate
    requests = []
    for n, (row, prefix) in enumerate(zip(rows, order)):
        requests.append(dict(
            key=f'{n:04d}', prefix=prefix, arrival=row['arrival_s'] * scale,
            deadline=DEADLINE, checkpoint=CHECKPOINT,
            short=draws[prefix]['short'][rng.randrange(8)],
            long=draws[prefix]['long'][rng.randrange(8)]))
    minutes = (requests[-1]['arrival'] - requests[0]['arrival']) / 60
    return requests, minutes


def miss_rate(results):
    return sum(1 - r['on_time'] for r in results) / len(results)


def extend_share(results):
    return sum(r['arm'] == 'long' for r in results) / len(results)


def anchor_lambda(values):
    # the constant rule extends while fewer than ANCHOR wait; this puts its
    # cutoff halfway between ANCHOR - 1 and ANCHOR waiting requests
    return SLOTS * values['constant'] / (ANCHOR - 0.5)


def shuffled(values, seed):
    # the same 58 values dealt to prefixes at random: same rule, random selection
    keys = sorted(values['other'])
    dealt = [values['other'][k] for k in keys]
    random.Random(seed).shuffle(dealt)
    return dict(zip(keys, dealt))


def policies(values, lam):
    constant = values['constant']
    return dict(
        fixed4k=fixed('short'), fixed8k=fixed('long'), arrival=arrival_rule(ARRIVAL_THRESHOLD),
        constant=value_rule('constant', lambda req: constant, lam),
        aware=value_rule('aware', lambda req: values['other'][req['prefix']], lam),
        # ceiling only: ranked by the same draws that decide the outcome
        aware_in_sample=value_rule('aware_in_sample', lambda req: values['own'][req['prefix']], lam))


def rate_curve(draws, rows):
    curve = []
    for rate in RATES:
        requests, _ = build_workload(draws, rows, rate)
        curve.append(dict(rate=rate,
                          miss_fixed4k=miss_rate(simulate(requests, fixed('short'))),
                          miss_fixed8k=miss_rate(simulate(requests, fixed('long')))))
    return curve


def calibrate():
    draws = load_draws(grades=False)
    values = load_values()
    rows, burst_trace = load_trace('burst')
    sustained_rows, sustained_trace = load_trace('sustained')

    # 1. arrival rate on the burst trace: fixed 8K should miss about TARGET_MISS.
    # the sustained trace is reported as context; it jumps from no misses to overload
    curve = rate_curve(draws, rows)
    chosen = min(curve, key=lambda p: abs(p['miss_fixed8k'] - TARGET_MISS))
    requests, minutes = build_workload(draws, rows, chosen['rate'])

    # 2. lambda from the anchor, then extension shares only (no grades are loaded)
    lam = anchor_lambda(values)
    shares = {name: extend_share(simulate(requests, policy))
              for name, policy in policies(values, lam).items()}
    controls = [extend_share(simulate(requests, value_rule('shuffled', lambda req, v=shuffled(values, s): v[req['prefix']], lam)))
                for s in range(SHUFFLES)]

    out = dict(
        seed=SEED, slots=SLOTS, checkpoint=CHECKPOINT, deadline=DEADLINE,
        trace='burst', target_miss_fixed8k=TARGET_MISS, anchor_waiting=ANCHOR,
        arrival_threshold=ARRIVAL_THRESHOLD,
        inputs=dict(draws_sha256=sha(DRAWS), values_sha256=sha(VALUES),
                    burst_sha256=sha(burst_trace), sustained_sha256=sha(sustained_trace)),
        rate_per_hour=chosen['rate'], requests=len(requests), minutes=minutes,
        miss_fixed4k=chosen['miss_fixed4k'], miss_fixed8k=chosen['miss_fixed8k'],
        lam=lam, constant_value=values['constant'], extend_share=shares,
        shuffled_extend_share=dict(mean=sum(controls) / len(controls), min=min(controls), max=max(controls)),
        values_other=values['other'], values_own=values['own'],
        rate_curve=curve, sustained_rate_curve=rate_curve(draws, sustained_rows))
    CALIBRATION.write_text(json.dumps(out, indent=1) + '\n')

    print(f'wrote {CALIBRATION.relative_to(ROOT)}')
    print(f'burst trace at {chosen["rate"]}/h over {minutes:.0f} min: fixed 8K misses '
          f'{chosen["miss_fixed8k"]:.1%}, fixed 4K {chosen["miss_fixed4k"]:.1%}')
    print(f'lambda {lam:.4f}: constant extends only while nobody waits')
    print('extension shares:', ', '.join(f'{k} {v:.1%}' for k, v in shares.items()))
    s = out['shuffled_extend_share']
    print(f'shuffled values ({SHUFFLES}): mean {s["mean"]:.1%}, range {s["min"]:.1%}-{s["max"]:.1%}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['calibrate'])
    parser.parse_args()
    calibrate()


if __name__ == '__main__':
    main()
