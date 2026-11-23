"""Retrospective, question-blocked diagnostics on sealed continuation forecasts."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np

repo = Path(sys.argv[1])
path = repo / "week7/hidden-state-probes/independent-validation/scoring-input.json"
rows = json.loads(path.read_text())["rows"]
qids = np.array([r["question"] for r in rows])
draws = np.array([r["draws"] for r in rows])
assert draws.shape == (329, 2, 8, 4)
pred = {name: np.array([r["forecast"][name] for r in rows])
        for name in ("prompt", "mean_4k")}
unique = sorted(set(qids), key=lambda q: hashlib.sha256(q.encode()).hexdigest())
cal_ids = set(unique[::3])
cal = np.isin(qids, list(cal_ids))
test = ~cal
labels = draws[..., 0].mean(axis=2)
cost = draws[..., 1].mean(axis=2)
seconds = draws[..., 3].mean(axis=2)
gain = labels[:, 1] - labels[:, 0]

def difference(values):
    return values[:, 1] - values[:, 0]

def pearson(a, b):
    return float(np.corrcoef(a, b)[0, 1])

def rank(x):
    values, inverse, counts = np.unique(x, return_inverse=True, return_counts=True)
    del values
    return (np.cumsum(counts) - (counts+1)/2)[inverse]

def spearman(a, b):
    return pearson(rank(a), rank(b))

def group_mean(x):
    return np.array([x[qids==q].mean() for q in qids])

def calibrate(x, y):
    centered = x[cal] - x[cal].mean()
    slope = np.sum(centered*(y[cal]-y[cal].mean())) / np.sum(centered**2)
    # Constrain the recalibration to preserve the original ordering.
    slope = max(0., slope)
    return y[cal].mean()+slope*(x-x[cal].mean()), float(slope)

def calibrate_arms(p):
    return np.column_stack([np.clip(calibrate(p[:,i], labels[:,i])[0],0,1)
                            for i in (0,1)])

def sibling_concordance(x, y, ids):
    pairs = np.array([np.flatnonzero(ids==qid) for qid in set(ids)
                      if np.sum(ids==qid)==2])
    a, b = pairs.T
    informative = y[a] != y[b]
    sign = np.sign((x[a]-x[b])*(y[a]-y[b]))[informative]
    return dict(n=len(sign), agreement=float(np.mean((sign+1)/2)),
                tied=int(np.sum(sign==0)))

def weights(score, extra_cost, allowance):
    order = np.argsort(-score, kind="stable")
    result = np.zeros(len(order))
    s = score[order]
    edges = np.r_[0, np.flatnonzero(np.diff(s)!=0)+1, len(s)]
    for start,end in zip(edges[:-1],edges[1:]):
        if allowance<=0:
            break
        ix = order[start:end]
        block_cost = extra_cost[ix].sum()
        fraction = min(1., allowance/block_cost)
        result[ix] = fraction
        allowance -= block_cost*fraction
    return result

assert (difference(cost)>0).all() and (difference(seconds)>0).all()
raw = {name:difference(value) for name,value in pred.items()}
arm_cal = {name:calibrate_arms(value) for name,value in pred.items()}
scores = {
    "uniform": np.zeros(len(rows)),
    "prompt_short_risk": 1-pred["prompt"][:,0],
    "prompt_gain": raw["prompt"],
    "prompt_arm_calibrated": difference(arm_cal["prompt"]),
    "prompt_calibrated_risk": 1-arm_cal["prompt"][:,0],
    "hidden_gain": raw["mean_4k"],
    "hidden_arm_calibrated": difference(arm_cal["mean_4k"]),
    "hidden_calibrated_risk": 1-arm_cal["mean_4k"][:,0],
    "hidden_question_mean_diagnostic": group_mean(raw["mean_4k"]),
    "hidden_within_diagnostic": raw["mean_4k"]-group_mean(raw["mean_4k"]),
}
# Prefill starts at a common 4K checkpoint. Within this artifact its input length
# provides a simple length proxy if both arm input counts agree.
assert np.all(draws[...,2] == draws[:,0,:1,2][:,None,:])
scores["prefill_length"] = draws[:,0,0,2]

def policy(x, ix, units, overhead):
    incremental = difference(units)[ix]
    allowance = .5*incremental.sum() - len(ix)*overhead
    w = weights(x[ix], incremental, allowance)
    return w

ix = np.flatnonzero(test)
added_tokens, added_seconds = difference(cost), difference(seconds)
all_groups = [np.flatnonzero(qids==q) for q in unique if q not in cal_ids]
rng = np.random.default_rng(20261120)
boot_ix = [np.concatenate([all_groups[i] for i in rng.integers(len(all_groups),size=len(all_groups))])
           for _ in range(1500)]

def compare(score, units, overhead=0., bootstrap=False, reference="prompt_gain"):
    w = policy(score, ix, units, overhead)
    baseline = policy(scores[reference],ix,units,0.)
    d = gain[ix]
    out = dict(accuracy=float(np.mean(labels[ix,0]+w*d)),
               lift_vs_reference_pp=float(100*np.mean((w-baseline)*d)),
               extension_rate=float(w.mean()),
               beneficial=float(w@(d>0)), harmful=float(w@(d<0)))
    if bootstrap:
        lift = [100*np.mean((policy(score,i,units,overhead)
                 - policy(scores[reference],i,units,0.))*gain[i]) for i in boot_ix]
        out["lift_ci95_pp"] = np.quantile(lift,[.025,.975]).tolist()
    return out

a, b = [difference(draws[:,:,sl,0].mean(axis=2)) for sl in (slice(0,4),slice(4,8))]
selected = (a[test]!=0)&(b[test]!=0)
report = dict(cohort=dict(calibration_questions=len(cal_ids), calibration_prefixes=int(cal.sum()),
                          evaluation_questions=len(all_groups), evaluation_prefixes=len(ix)),
              label_reliability=dict(pearson_halves=pearson(a[test],b[test]),
                  spearman_halves=spearman(a[test],b[test]),
                  nonzero_both=int(selected.sum()),
                  sign_agreement=float(np.mean(np.sign(a[test][selected])==np.sign(b[test][selected])))),
              raw_calibration={}, scores={}, policies={})
for name,p in pred.items():
    g,slope = calibrate(raw[name], gain)
    cp = arm_cal[name]
    report["raw_calibration"][name] = dict(
        raw_bias=float(np.mean(raw[name][test]-gain[test])), gain_slope=slope,
        raw_gain_mse=float(np.mean((raw[name][test]-gain[test])**2)),
        calibrated_gain_mse=float(np.mean((g[test]-gain[test])**2)),
        arm_calibrated_gain_mse=float(np.mean((difference(cp)[test]-gain[test])**2)),
        raw_arm_brier=(np.mean((p[test,:,None]-draws[test,:,:,0])**2,axis=(0,2))).tolist(),
        calibrated_arm_brier=(np.mean((cp[test,:,None]-draws[test,:,:,0])**2,axis=(0,2))).tolist())
for name,x in scores.items():
    report["scores"][name] = dict(
        rank_halves=[spearman(x[test],half[test]) if len(set(x[test]))>1 else None for half in (a,b)],
        within_held=sibling_concordance(x[test],gain[test],qids[test]))
    report["policies"][name] = dict(tokens=compare(x,cost,bootstrap=True),
                                    call_seconds=compare(x,seconds))
report["hidden_overhead_sensitivity"] = {
    str(overhead):compare(scores["hidden_gain"],cost,overhead) for overhead in (25,100,250)}
report["calibrated_hidden_vs_uniform"] = {
    str(overhead):compare(scores["hidden_arm_calibrated"],cost,overhead,True,"uniform")
    for overhead in (0,25,100,250)}
report["label_reliability"]["within_question_half_agreement"] = sibling_concordance(
    a[test],b[test],qids[test])
report["label_reliability"]["held_fixed_accuracy"] = labels[test].mean(axis=0).tolist()
def head_to_head(candidate, reference, head_cost=0., reference_cost=0.):
    def allocation_delta(indices):
        return (policy(scores[candidate],indices,cost,head_cost)
                - policy(scores[reference],indices,cost,reference_cost))
    dw = allocation_delta(ix)
    ci = np.quantile([100*np.mean(allocation_delta(i)*gain[i]) for i in boot_ix],
                     [.025,.975])
    changed = np.abs(dw)>1e-9
    return dict(
        lift_pp=float(100*np.mean(dw*gain[ix])),
        ci95_pp=ci.tolist(),
        draw_half_lifts_pp=[float(100*np.mean(dw*half[ix])) for half in (a,b)],
        ext_weight_shifted_in=float(np.maximum(dw,0).sum()),
        ext_weight_shifted_out=float(np.maximum(-dw,0).sum()),
        affected_prefixes=int(changed.sum()),
        gained_improvement=float(dw@np.maximum(gain[ix],0)),
        added_regression=float(dw@np.maximum(-gain[ix],0)),
    )

report["matched_heads"] = {
    prefix: {
        str(fee):head_to_head(f"{prefix}_arm_calibrated",f"{prefix}_calibrated_risk",fee,fee)
        for fee in (0,25,100,250)}
    for prefix in ("prompt","hidden")
}
report["feature_increment"] = {
    str(fee):{
        name:head_to_head("hidden_arm_calibrated",name,fee,0)
        for name in ("uniform","prefill_length","prompt_calibrated_risk","prompt_arm_calibrated")}
    for fee in (0,25,100,250)
}
gain_name, risk_name = "hidden_arm_calibrated", "hidden_calibrated_risk"
count_w = {name:weights(scores[name][ix],np.ones(len(ix)),len(ix)//2)
           for name in (gain_name,risk_name)}
count_dw = count_w[gain_name]-count_w[risk_name]
token_dw = policy(scores[gain_name],ix,cost,0)-policy(scores[risk_name],ix,cost,0)
group_gain = group_mean(gain)
report["hidden_gain_vs_risk_mechanism"] = {
    "equal_count_lift_pp":float(100*np.mean(count_dw*gain[ix])),
    "equal_count_half_lifts_pp":[float(100*np.mean(count_dw*half[ix])) for half in (a,b)],
    "equal_count_extra_tokens_per_prefix":{
        name:float(np.mean(w*added_tokens[ix])) for name,w in count_w.items()},
    "matched_token_contribution_question_mean_pp":float(100*np.mean(token_dw*group_gain[ix])),
    "matched_token_contribution_within_question_pp":float(100*np.mean(token_dw*(gain-group_gain)[ix])),
}
print(json.dumps(report,indent=2))
