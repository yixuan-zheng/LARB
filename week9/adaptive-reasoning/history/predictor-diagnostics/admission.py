"""Fit fixed-size prefill heads on archived questions and score disjoint questions."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

run, published = map(Path, sys.argv[1:])
data = json.loads(published.read_text())
seal = json.loads((run / "forecast-seal.json").read_text())
for field, filename in (("prefixes", "prefix-selection.json"), ("features", "features.npz"),
                        ("forecasts", "forecasts.json")):
    assert hashlib.sha256((run / filename).read_bytes()).hexdigest() == seal[field]

rows = data["rows"]
forecast = json.loads((run / "forecasts.json").read_text())
assert [r["key"] for r in rows] == [r["key"] for r in forecast]
for row, proof in zip(rows, forecast):
    assert row["forecast"] == proof["forecast"]
x = np.load(run / "features.npz")["X"][:, 0, :].astype(float)
draws = np.array([row["draws"] for row in rows])
assert draws.shape == (329, 2, 8, 4) and x.shape == (329, 2560)
assert np.isfinite(x).all()
qids = np.array([row["question"] for row in rows])
questions = sorted(set(qids), key=lambda q: hashlib.sha256(q.encode()).hexdigest())
groups = [np.flatnonzero(qids == question) for question in questions]
for ix in groups:
    np.testing.assert_allclose(x[ix], np.broadcast_to(x[ix[0]], x[ix].shape), atol=1e-6, rtol=1e-6)
fit_ids = set(questions[::3])
fit_group = np.array([q in fit_ids for q in questions])
held = [ix for q, ix in zip(questions, groups) if q not in fit_ids]
test = np.concatenate(held)
fit = np.isin(qids, list(fit_ids))

rates = draws[..., 0].mean(axis=2)
costs = draws[..., 1].mean(axis=2)
assert np.all(draws[...,2] == draws[:,0,:1,2][:,None,:])
delta = rates[:, 1] - rates[:, 0]
extra = costs[:, 1] - costs[:, 0]
assert (extra > 0).all()

# Same four-PC ridge specification as the earlier 29-question diagnostic.
# Fit by question so a second surviving prefix adds precision, not sample weight.
qx = np.stack([x[i[0]] for i in groups])
qp = np.stack([rates[i].mean(axis=0) for i in groups])
target = np.column_stack((qp[:, 1] - qp[:, 0], 1 - qp[:, 0]))
train = qx[fit_group]
center = train.mean(axis=0)
_, singular, basis = np.linalg.svd(train-center, full_matrices=False)
scale = singular[:4] / np.sqrt(len(train))
z = ((x-center) @ basis[:4].T) / scale
z_train = ((train-center) @ basis[:4].T) / scale
y = target[fit_group]
intercept = y.mean(axis=0)
beta = np.linalg.solve(z_train.T @ z_train+len(train)*np.eye(4), z_train.T @ (y-intercept))
head = z @ beta + intercept

old = np.array([r["forecast"]["prompt"] for r in rows])
def calibrate(p, y):
    centered = p[fit] - p[fit].mean()
    slope = max(0., centered @ (y[fit]-y[fit].mean()) / (centered @ centered))
    return np.clip(y[fit].mean()+slope*(p-p[fit].mean()), 0, 1)

old_cal = [calibrate(old[:, i], rates[:, i]) for i in range(2)]
scores = {
    "direct_gain": head[:, 0],
    "same_feature_risk": head[:, 1],
    "old_probability_gain": old[:, 1]-old[:, 0],
    "old_calibrated_gain": old_cal[1]-old_cal[0],
    "old_risk": 1-old_cal[0],
    "length": draws[:, 0, 0, 2],
    "uniform": np.zeros(len(rows)),
}
halves = [np.diff(draws[:, :, s, 0].mean(axis=2), axis=1).ravel()
          for s in (slice(0, 4), slice(4, 8))]

def weights(name, ix, fee=0., matched_count=False):
    costs = np.ones(len(ix)) if matched_count else extra[ix]
    budget = .5*costs.sum()-fee*len(ix)
    scoreset = scores[name][ix]
    order = np.argsort(-scoreset, kind="stable")
    ordered = scoreset[order]
    edges = np.r_[0, np.flatnonzero(np.diff(ordered)!=0)+1, len(ix)]
    w = np.zeros(len(ix))
    for begin,end in zip(edges[:-1],edges[1:]):
        if budget <= 0:
            break
        block = order[begin:end]
        price = costs[block].sum()
        w[block] = min(1., budget/price)
        budget -= price*w[block[0]]
    return w

def rank(values):
    _, inverse, counts = np.unique(values, return_inverse=True, return_counts=True)
    return (np.cumsum(counts)-(counts+1)/2)[inverse]

def rank_halves(name):
    if len(set(scores[name][test])) == 1:
        return [None, None]
    return [float(np.corrcoef(rank(scores[name][test]),rank(h[test]))[0,1]) for h in halves]

def evaluate(name):
    w = weights(name,test)
    return dict(accuracy=float(np.mean(rates[test,0]+w*delta[test])),
                extension_rate=float(w.mean()), rank_draw_halves=rank_halves(name),
                gains=float(w@np.maximum(delta[test],0)),
                harm=float(w@np.maximum(-delta[test],0)))

rng = np.random.default_rng(356)
bootstrap = [np.concatenate([held[i] for i in rng.integers(len(held),size=len(held))])
             for _ in range(2500)]
def compare(reference, fee=0, matched_count=False):
    def diff(ix):
        return (weights("direct_gain",ix,fee,matched_count)
                - weights(reference,ix,0,matched_count))
    w = diff(test)
    return dict(lift_pp=float(100*np.mean(w*delta[test])),
                halves_pp=[float(100*np.mean(w*h[test])) for h in halves],
                ci95_pp=np.quantile([100*np.mean(diff(i)*delta[i]) for i in bootstrap],[.025,.975]).tolist())

result = dict(fit_questions=int(fit_group.sum()), held_questions=len(held),
              held_prefixes=len(test), fixed_accuracy=rates[test].mean(axis=0).tolist(),
              compared_at="half of observed available incremental suffix tokens",
              targets="4K checkpoint outcomes averaged by question among eligible prefixes",
              scores={name:evaluate(name) for name in scores},
              comparisons={n:compare(n) for n in scores if n!="direct_gain"},
              overhead_vs_uniform={str(fee):compare("uniform",fee) for fee in (25,100,250)},
              matched_count_vs_risk=compare("same_feature_risk",matched_count=True),
              input_hashes=seal)
print(json.dumps(result,indent=2))
