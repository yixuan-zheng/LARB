"""Cost-matched view of Experiment 3 (hidden-state probe vs prompt-only, protected questions).

Run from the repository root (needs numpy):
    python3 -B week7/scoring/protected.py

The frozen experiment compared the two probes at the same extension count. This
adds the same comparison at matched realized cost and at equal accuracy, on
generated suffix tokens and on measured call seconds. Both probes read hidden
states the served model already computes, so their own cost is taken as zero.
"""
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
EXP3 = ROOT / 'week7/hidden-state-probes/independent-validation'
OUT = Path(__file__).resolve().parent / 'protected-summary.json'
COSTS = {'suffix tokens': 1, 'call seconds': 3}  # index into each draw record


def curve(score, delta, extra):
    # expected gain and extra cost from extending the top N, for every N from 0 to n.
    # tied scores at the cutoff share the remaining slots evenly, as in the frozen scorer
    order = np.argsort(-score, kind='stable')
    s, d, c = score[order], delta[order], extra[order]
    starts = np.flatnonzero(np.r_[True, s[1:] != s[:-1]])
    sizes = np.diff(np.r_[starts, len(s)])
    cum_d, cum_c = np.r_[0, np.cumsum(d)], np.r_[0, np.cumsum(c)]
    group_d = cum_d[starts + sizes] - cum_d[starts]
    group_c = cum_c[starts + sizes] - cum_c[starts]
    n = np.arange(len(s) + 1)
    g = np.clip(np.searchsorted(starts + sizes, n, side='left'), 0, len(starts) - 1)
    frac = np.clip((n - starts[g]) / sizes[g], 0, 1)
    return cum_d[starts[g]] + frac * group_d[g], cum_c[starts[g]] + frac * group_c[g]


def compare(rates, costs, scores, k=None):
    # returns the endpoints, then the (correct, cost) curves for q and p
    delta = rates[:, 1] - rates[:, 0]
    base_correct, base_cost = rates[:, 0].sum(), costs[:, 0].sum()
    extra = costs[:, 1] - costs[:, 0]
    (qd, qc), (pd, pc) = [curve(scores[name], delta, extra) for name in ('prompt', 'mean_4k')]
    qd, pd, qc, pc = qd + base_correct, pd + base_correct, qc + base_cost, pc + base_cost
    k = len(delta) // 2 if k is None else k
    full = rates[:, 1].sum()  # all-long accuracy
    return dict(
        count_lift=pd[k] - qd[k],
        count_cost_diff=pc[k] - qc[k],
        # matched cost: p's best accuracy within q's half-allocation spend
        matched_cost_lift=pd[pc <= qc[k] + 1e-9].max() - qd[k],
        # equal accuracy: cost p saves reaching q's half-allocation accuracy
        equal_acc_saving=qc[k] - pc[pd >= qd[k] - 1e-9].min(),
        # equal accuracy at all-long correctness
        full_acc_saving=qc[qd >= full - 1e-9].min() - pc[pd >= full - 1e-9].min(),
    ), (qd, qc, pd, pc)


def main():
    data = json.loads((EXP3 / 'scoring-input.json').read_text())
    rows = data['rows']
    draws = np.asarray([r['draws'] for r in rows], dtype=float)
    assert draws.shape == (329, 2, 8, 4)
    rates = draws[:, :, :, 0].mean(axis=2)
    scores = {name: np.array([r['forecast'][name][1] - r['forecast'][name][0] for r in rows])
              for name in ('prompt', 'mean_4k')}
    question = np.array([r['question'] for r in rows])
    cohort = sorted(r['id'] for r in json.loads((EXP3 / 'cohort-v1.json').read_text())['selected'])
    groups = [np.flatnonzero(question == q) for q in cohort]  # empty groups kept, as in the frozen run
    n = len(rows)

    summary = {}
    for label, column in COSTS.items():
        costs = draws[:, :, :, column].mean(axis=2)
        point, (qd, qc, pd, pc) = compare(rates, costs, scores)
        if column == 1:
            # reproduce the published half-allocation numbers first
            k = n // 2
            assert abs(qd[k] - 159.5) < 1e-9 and abs(pd[k] - 166.875) < 1e-9
            assert abs(qc[k] - 1050962.6875) < 1e-6 and abs(pc[k] - 1048927.0) < 1e-6

        # same generator, seed and resampling as evaluate_full.py, so the count interval matches
        rng = np.random.default_rng(356)
        boot = []
        for _ in range(10000):
            ix = np.concatenate([groups[j] for j in rng.integers(len(groups), size=len(groups))])
            if len(ix):
                stats, _ = compare(rates[ix], costs[ix], {k2: v[ix] for k2, v in scores.items()})
                boot.append({k2: v / len(ix) for k2, v in stats.items()})
        result = {}
        for key, value in point.items():
            low, high = np.quantile([b[key] for b in boot], [.025, .975]) * n
            result[key] = dict(observed=float(value), low=float(low), high=float(high))
        summary[label] = result

    count = summary['suffix tokens']['count_lift']
    assert abs(100 * count['low'] / n - -0.1529051987767584) < 1e-9  # published ci95_pp
    assert abs(100 * count['high'] / n - 4.981710636967396) < 1e-9
    OUT.write_text(json.dumps(summary, indent=2) + '\n')

    names = {
        'count_lift': 'P-Q correct at same extension count (primary)',
        'count_cost_diff': 'P-Q cost at same extension count',
        'matched_cost_lift': 'P-Q correct at Q\'s half-allocation cost',
        'equal_acc_saving': 'cost P saves reaching Q\'s half-allocation accuracy',
        'full_acc_saving': 'cost P saves reaching all-long accuracy',
    }
    print(f'experiment 3, {n} eligible checkpoints, 10,000 question-grouped resamples\n'
          '(intervals in cohort-sized units: answers, tokens or seconds across all checkpoints)')
    for label, result in summary.items():
        print(f'\ncost = {label}')
        for key, name in names.items():
            r = result[key]
            print(f'   {name:52} {r["observed"]:12,.1f}   [{r["low"]:12,.1f}, {r["high"]:12,.1f}]')
    print(f'\nwrote {OUT.name}')


if __name__ == '__main__':
    main()
