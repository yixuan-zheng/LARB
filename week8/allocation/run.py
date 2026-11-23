"""Build the allocation replay workload, calibrate it, and run the frozen comparison.

Run from the repository root after build_draws.py:
    python3 -B week8/allocation/run.py calibrate   # timing only -> calibration.json
    python3 -B week8/allocation/run.py compare     # PROTOCOL.md rules -> results/ (~20 min)

Every arrival in a scaled-serving trace becomes one Experiment 2 checkpoint
request. Prefixes are dealt in shuffled rounds so each appears about equally,
and each request gets one random short draw and one random long draw. The same
requests are replayed under every policy, so policy differences are paired.
Calibration loads the draws without grades: it sees token counts only. The
compare stage refuses to run unless PROTOCOL.md is committed and every frozen
input still has the hash it lists.
"""
import argparse
import csv
import hashlib
import json
import random
import re
import statistics
import subprocess
from collections import defaultdict
from pathlib import Path

from sim import CHECKPOINT, DEADLINE, SLOTS, arrival_rule, fixed, simulate, summarize, value_rule

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
DRAWS = HERE / 'draws.csv'
VALUES = ROOT / 'week7/continuation-sampling/results/full-summary.json'  # until the frozen export lands
TRACES = ROOT / 'week7/scaled-serving/artifacts/traces'
CALIBRATION = HERE / 'calibration.json'
PROTOCOL = HERE / 'PROTOCOL.md'
RESULTS = HERE / 'results'

SEED = 8222
RATES = range(100, 1001, 20)  # requests per hour
TARGET_MISS = 0.25     # fixed 8K misses about a quarter of deadlines, inside the 15-40% band
ANCHOR = 1             # the constant rule extends only while fewer than 1 wait
SHUFFLES = 50          # shuffled-value controls checked during calibration
ARRIVAL_THRESHOLD = 8  # p1 pressure threshold: 8 waiting for 32 slots

# compare stage, all from PROTOCOL.md
BOOT_SEED = 8226
PRIMARY_REPS, SELECTION_REPS, CELL_REPS = 10_000, 2_000, 1_000
SHUFFLE_SEEDS = range(20)
SWEEP = (1, 2, 4, 8)  # constant extends only while fewer than this many wait
TABLE_TOKENS = 2_994_681 + 3_932_384  # experiment 2 generated + input tokens
TABLE_QUESTIONS = 29


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


def build_workload(draws, rows, rate, seed=SEED, deck=None):
    """Rescale a trace to `rate` requests per hour and fill it with checkpoint requests.

    The random draws do not depend on the rate, so two rates replay the same
    requests on a different clock. `deck` replaces the 58 prefixes with a
    bootstrap resample, duplicates included.
    """
    rng = random.Random(seed)
    prefixes = sorted(deck if deck is not None else draws)
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


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True, text=True, check=True).stdout.strip()


def check_freeze():
    # the input table in PROTOCOL.md is the one place the frozen hashes live
    frozen = {}
    for line in PROTOCOL.read_text().splitlines():
        match = re.match(r'\| \[[^\]]+\]\(([^)]+)\).*\| `([0-9a-f]{64})` \|$', line)
        if match:
            frozen[(HERE / match.group(1)).resolve()] = match.group(2)
    assert len(frozen) == 6, 'expected six frozen inputs in PROTOCOL.md'
    for path, expected in frozen.items():
        assert sha(path) == expected, f'{path.name} changed since the freeze'
    assert not git('status', '--porcelain', '--', str(PROTOCOL)), 'PROTOCOL.md must be committed and unchanged'
    commit = git('log', '-1', '--format=%H', '--', str(PROTOCOL))
    assert commit, 'PROTOCOL.md is not committed'
    return commit, {str(p.relative_to(ROOT)): h for p, h in frozen.items()}


def frozen_values():
    calibration = json.loads(CALIBRATION.read_text())
    values = dict(own=calibration['values_own'], other=calibration['values_other'],
                  constant=calibration['constant_value'])
    assert values == load_values() and calibration['lam'] == anchor_lambda(values)
    return calibration, values


def shuffled_policies(values, lam):
    return [value_rule(f'shuffled-{s}', lambda req, v=shuffled(values, s): v[req['prefix']], lam)
            for s in SHUFFLE_SEEDS]


def setting(rate, **change):
    base = dict(trace='burst', rate=rate, seed=SEED, speed=1.0, lag=0.0, deadline=DEADLINE)
    base.update(change)
    return base


def cells(rate):
    out = {'rate x0.9': setting(rate * 0.9), 'rate x1.1': setting(rate * 1.1),
           'speed x0.75': setting(rate, speed=0.75), 'speed x1.25': setting(rate, speed=1.25),
           'lag 5 s': setting(rate, lag=5.0), 'lag 20 s': setting(rate, lag=20.0),
           'deadline 180 s': setting(rate, deadline=180.0)}
    out.update({f'seed {s}': setting(rate, seed=s) for s in range(8223, 8228)})
    return out


def workload(draws, traces, s, deck=None):
    requests, minutes = build_workload(draws, traces[s['trace']], s['rate'], s['seed'], deck)
    if s['deadline'] != DEADLINE:
        requests = [dict(r, deadline=s['deadline']) for r in requests]
    return requests, minutes


def replay(requests, policy, s):
    return simulate(requests, policy, speed=s['speed'], lag=s['lag'])


def good(requests, policy, s):
    return sum(r['good'] for r in replay(requests, policy, s))


def describe(results, minutes):
    out = summarize(results, minutes)
    latency = sorted(r['latency'] for r in results if r['scored'])
    out.update(latency_p50=latency[len(latency) // 2],
               latency_p90=latency[int(0.9 * (len(latency) - 1))],
               slot_seconds=sum(r['finish'] - r['start'] for r in results if r['scored']))
    return out


def point(draws, traces, s, values, lam):
    # every policy once on one setting, plus the three frozen contrasts
    requests, minutes = workload(draws, traces, s)
    named = {name: describe(replay(requests, p, s), minutes) for name, p in policies(values, lam).items()}
    shuffles = [good(requests, p, s) for p in shuffled_policies(values, lam)]
    named['shuffled'] = dict(good=statistics.mean(shuffles), good_min=min(shuffles), good_max=max(shuffles))
    aware = named['aware']['good']
    contrasts = dict(primary=aware - named['constant']['good'],
                     selection=aware - named['shuffled']['good'],
                     fixed_check=aware - max(named['fixed4k']['good'], named['fixed8k']['good']))
    return dict(setting=s, policies=named, contrasts=contrasts)


def decks(values, reps):
    # resample questions with replacement; a drawn question brings both prefixes
    rng = random.Random(BOOT_SEED)
    questions = sorted({key.split('-')[0] for key in values['other']})
    out = []
    for _ in range(reps):
        picks = [rng.choice(questions) for _ in questions]
        out.append([f'{q}-b{b}' for q in picks for b in (0, 1)])
    return out


def interval(diffs):
    # same percentile convention as the week 6 and week 7 bootstraps
    s, n = sorted(diffs), len(diffs)
    return [s[round(0.025 * n) - 1], s[round(0.975 * n) - 1]]


def bootstrap(draws, traces, s, values, lam, resamples, selection=False):
    p = policies(values, lam)
    controls = shuffled_policies(values, lam) if selection else []
    diffs = []
    for deck in resamples:
        requests, _ = workload(draws, traces, s, deck)
        aware = good(requests, p['aware'], s)
        if selection:
            diffs.append(aware - statistics.mean(good(requests, c, s) for c in controls))
        else:
            diffs.append(aware - good(requests, p['constant'], s))
    return interval(diffs)


def question_accounting(draws, traces, s, values, lam):
    requests, _ = workload(draws, traces, s)
    p = policies(values, lam)
    constant = {r['key']: r for r in replay(requests, p['constant'], s)}
    aware = {r['key']: r for r in replay(requests, p['aware'], s)}
    rows = defaultdict(lambda: dict(requests=0, good_constant=0, good_aware=0,
                                    extended_constant=0, extended_aware=0))
    for req in requests:
        question = req['prefix'].split('-')[0]
        row = rows[question]
        row['requests'] += 1
        row['good_constant'] += constant[req['key']]['good']
        row['good_aware'] += aware[req['key']]['good']
        row['extended_constant'] += constant[req['key']]['arm'] == 'long'
        row['extended_aware'] += aware[req['key']]['arm'] == 'long'
    table = []
    for question in sorted(rows):
        row = rows[question]
        table.append(dict(question_id=f'aime2026-{int(question[1:]):03d}', **row,
                          difference=row['good_aware'] - row['good_constant'],
                          value_b0=values['own'][f'{question}-b0'], value_b1=values['own'][f'{question}-b1']))
    gains = sum(aware[k]['good'] and not constant[k]['good'] for k in aware)
    losses = sum(constant[k]['good'] and not aware[k]['good'] for k in aware)
    summary = dict(questions_gaining=sum(r['difference'] > 0 for r in table),
                   questions_losing=sum(r['difference'] < 0 for r in table),
                   questions_tied=sum(r['difference'] == 0 for r in table),
                   requests_gained=gains, requests_lost=losses,
                   largest=sorted(table, key=lambda r: -abs(r['difference']))[:5])
    return table, summary


def sweep(draws, traces, s, values):
    out = []
    requests, _ = workload(draws, traces, s)
    for waiting in SWEEP:
        lam = SLOTS * values['constant'] / (waiting - 0.5)
        p = policies(values, lam)
        c, a = replay(requests, p['constant'], s), replay(requests, p['aware'], s)
        out.append(dict(anchor_waiting=waiting, lam=lam,
                        good_constant=sum(r['good'] for r in c), good_aware=sum(r['good'] for r in a),
                        extended_constant=extend_share(c), extended_aware=extend_share(a),
                        difference=sum(r['good'] for r in a) - sum(r['good'] for r in c)))
    return out


def write_csv(path, rows):
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def compare():
    commit, hashes = check_freeze()
    out_json = RESULTS / 'compare.json'
    if out_json.exists():
        raise FileExistsError(f'{out_json.relative_to(ROOT)}: move published results aside to reproduce')
    calibration, values = frozen_values()
    lam, rate = calibration['lam'], calibration['rate_per_hour']
    draws = load_draws(grades=True)
    traces = {name: load_trace(name)[0] for name in ('burst', 'sustained')}
    primary = setting(rate)

    print('primary run', flush=True)
    main_run = point(draws, traces, primary, values, lam)
    resamples = decks(values, PRIMARY_REPS)
    print(f'primary bootstrap ({PRIMARY_REPS:,})', flush=True)
    main_run['primary_95'] = bootstrap(draws, traces, primary, values, lam, resamples)
    print(f'selection bootstrap ({SELECTION_REPS:,} x {len(SHUFFLE_SEEDS)} shuffles)', flush=True)
    main_run['selection_95'] = bootstrap(draws, traces, primary, values, lam,
                                         resamples[:SELECTION_REPS], selection=True)
    table, accounting = question_accounting(draws, traces, primary, values, lam)

    grid = {}
    for name, s in cells(rate).items():
        print(f'cell {name}', flush=True)
        grid[name] = point(draws, traces, s, values, lam)
        grid[name]['primary_95'] = bootstrap(draws, traces, s, values, lam, resamples[:CELL_REPS])

    print('context runs', flush=True)
    context = dict(sustained=point(draws, traces, setting(rate, trace='sustained'), values, lam),
                   lambda_sweep=sweep(draws, traces, primary, values))

    # cost accounting in served-token equivalents (protocol section 5)
    named = main_run['policies']
    saved = (named['constant']['tokens'] - named['aware']['tokens']) / named['aware']['requests']
    per_question = TABLE_TOKENS / TABLE_QUESTIONS
    cost = dict(table_tokens=TABLE_TOKENS, table_tokens_per_question=per_question,
                tokens_saved_per_request=saved,
                break_even_requests_per_question=per_question / saved if saved > 0 else None)

    c = main_run['contrasts']
    conditions = dict(a_primary_lower_bound_above_0=main_run['primary_95'][0] > 0,
                      b_primary_positive_in_all_cells=all(g['contrasts']['primary'] > 0 for g in grid.values()),
                      c_selection_positive=c['selection'] > 0,
                      d_fixed_check_not_negative=c['fixed_check'] >= 0)
    if c['primary'] <= 0 or c['selection'] <= 0:
        verdict = 'stop'
    elif conditions['a_primary_lower_bound_above_0'] and conditions['b_primary_positive_in_all_cells'] \
            and conditions['d_fixed_check_not_negative']:
        verdict = 'advance, if the serving go/no-go qualifies a pool and deadline (condition e)'
    else:
        verdict = 'replay-only'

    RESULTS.mkdir(exist_ok=True)
    out_json.write_text(json.dumps(dict(
        protocol_commit=commit, frozen_inputs=hashes, rate_per_hour=rate, lam=lam,
        primary=main_run, question_accounting=accounting, cells=grid, context=context,
        cost=cost, conditions=conditions, verdict=verdict), indent=1) + '\n')
    write_csv(RESULTS / 'questions.csv', table)
    write_csv(RESULTS / 'cells.csv', [
        dict(cell=name, primary=g['contrasts']['primary'], primary_lo=g['primary_95'][0],
             primary_hi=g['primary_95'][1], selection=g['contrasts']['selection'],
             fixed_check=g['contrasts']['fixed_check'],
             good_constant=g['policies']['constant']['good'], good_aware=g['policies']['aware']['good'],
             good_fixed4k=g['policies']['fixed4k']['good'], good_fixed8k=g['policies']['fixed8k']['good'])
        for name, g in grid.items()])

    print(f'wrote {RESULTS.relative_to(ROOT)}/compare.json, questions.csv, cells.csv')
    print(f'primary: aware - constant = {c["primary"]:+d} good answers, 95% {main_run["primary_95"]}')
    print(f'selection: aware - shuffled = {c["selection"]:+.2f}, 95% {main_run["selection_95"]}')
    print(f'fixed check: aware - best fixed = {c["fixed_check"]:+d}')
    print(f'verdict: {verdict}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', choices=['calibrate', 'compare'])
    args = parser.parse_args()
    calibrate() if args.stage == 'calibrate' else compare()


if __name__ == '__main__':
    main()
