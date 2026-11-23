"""Development-only outcome and allocation diagnostics for full requests."""

import json
import sys
from pathlib import Path

import numpy as np

root = Path(sys.argv[1])
data = json.loads((root/"freeze.json").read_text())
ids = [q["question_id"] for q in data["questions"]]
keys = [(qid,cap,seed) for qid in ids for cap in data["budgets"] for seed in data["seeds"]]
paths = [root/"smoke/solves"/f"admission--fixed{cap}--{qid}--{seed}.json"
         for qid,cap,seed in keys]
completed = [json.loads(p.read_text()) for p in paths if p.exists()]
print(json.dumps({"planned":len(paths),"completed":len(completed)}),flush=True)
if len(completed)!=len(paths):
    sys.exit("Grid incomplete")
assert all((r["question_id"],r["budget"],r["seed"])==k and r["complete"]
           for r,k in zip(completed,keys))

def grid(field):
    return np.array([field(r) for r in completed]).reshape(len(ids),2,-1)
correct = grid(lambda r:int(r["correct"]))
tokens = grid(lambda r:r["prompt_tokens"]+r["output_tokens"])
caps = grid(lambda r:r["audit"]["reason"]=="answer_cap")
early = grid(lambda r:r["audit"]["close_index"] is not None and
             not r["audit"]["forced"] and r["audit"]["close_index"]<4096)
rates = correct.mean(axis=2)
gain = rates[:,1]-rates[:,0]
cost = tokens.mean(axis=2)
added = cost[:,1]-cost[:,0]
a,b = [np.diff(correct[:,:,lo:hi].mean(axis=2),axis=1).ravel() for lo,hi in ((0,2),(2,4))]
draw_halves_r = float(np.corrcoef(a,b)[0,1]) if a.std() and b.std() else None
result = dict(
    planned=len(paths), completed=len(paths), fixed_correct=correct.sum(axis=(0,2)).tolist(),
    fixed_mean_tokens=cost.mean(axis=0).tolist(), early=early.sum(axis=(0,2)).tolist(),
    answer_caps=caps.sum(axis=(0,2)).tolist(), gain_mean=float(gain.mean()),
    per_question_gain_sd=float(gain.std(ddof=1)), draw_halves_r=draw_halves_r,
    positive_draw_halves=int(np.sum((a>0)&(b>0))),
    negative_draw_halves=int(np.sum((a<0)&(b<0))),
    preemptions=sum(r["preemptions"] for r in completed))
if not (root/"prefill.npz").exists():
    print(json.dumps(result,indent=2))
    sys.exit(0)

archive = np.load(root/"prefill.npz")
assert archive["keys"].tolist()==ids
x = archive["X"].astype(float)
weights = np.load(root/"repo/week7/hidden-state-probes/independent-validation/probes-v1.npz")
logits = ((x @ weights["prompt_components"].T - weights["prompt_projected_mean"])
          @ weights["prompt_coef"].T + weights["prompt_intercept"])

def sigmoid(s):
    return 1/(1+np.exp(-np.clip(s,-40,40)))

p = sigmoid(logits)
scores = {"old_gain":p[:,1]-p[:,0],"old_risk":1-p[:,0],
          "length":np.array([q["prompt_tokens"] for q in data["questions"]])}
folds = np.array([data["folds"][qid] for qid in ids])
for name in ("shared_binomial_gain","shared_binomial_risk","ridge_gain"):
    scores[name] = np.zeros(len(ids))

def design(z):
    base = np.c_[np.ones(len(z)),z]
    return np.vstack([np.c_[base,np.zeros_like(base)],np.c_[base,base]])

for fold in sorted(set(folds)):
    train = folds != fold
    center = x[train].mean(axis=0)
    _,s,v = np.linalg.svd(x[train]-center,full_matrices=False)
    z = (x-center)@v[:4].T/(s[:4]/np.sqrt(train.sum()))
    d = design(z[train])
    y = rates[train].T.ravel()
    penalty = np.diag([.01,1,1,1,1,.01,2,2,2,2])
    coefficient = np.zeros(d.shape[1])
    for _ in range(35):
        prob = sigmoid(d@coefficient)
        hessian = d.T@(d*(prob*(1-prob))[:,None])+penalty
        step = np.linalg.solve(hessian,d.T@(y-prob)-penalty@coefficient)
        coefficient += step
        if np.linalg.norm(step)<1e-8:
            break
    fitted = sigmoid(design(z[~train])@coefficient).reshape(2,-1)
    scores["shared_binomial_gain"][~train] = fitted[1]-fitted[0]
    scores["shared_binomial_risk"][~train] = 1-fitted[0]
    zt = z[train]
    y_mean = gain[train].mean()
    ridge = np.linalg.solve(zt.T@zt+train.sum()*np.eye(4),zt.T@(gain[train]-y_mean))
    scores["ridge_gain"][~train] = z[~train]@ridge+y_mean

def allocate(score,tokens_budget):
    # Realized-cost replay, with symmetric fractional allocation for tied scores.
    chosen=np.zeros(len(score))
    for value in sorted(set(score),reverse=True):
        indices=np.flatnonzero(score==value)
        amount=added[indices].sum()
        fraction=1. if amount<=0 else np.clip(tokens_budget/amount,0,1)
        chosen[indices]=fraction
        tokens_budget-=fraction*amount
    return chosen

def policy_metrics(score,fee):
    selected=allocate(score,.5*added.sum()-len(ids)*fee)
    return dict(accuracy=float(np.mean(rates[:,0]+selected*gain)),
        half_accuracy=[float(np.mean(correct[:,0,lo:hi].mean(axis=1)+selected*target))
                       for lo,hi,target in ((0,2,a),(2,4,b))],
        extensions=float(selected.sum()),mean_tokens_including_fee=float(np.mean(cost[:,0]+selected*added)+fee))
result["replay"] = {name:policy_metrics(values,0) for name,values in scores.items()}
result["uniform"] = policy_metrics(np.zeros(len(ids)),0)
result["binomial_gain_overhead"] = {str(fee):policy_metrics(scores["shared_binomial_gain"],fee)
                                    for fee in (25,100,250)}
result["prefill_seconds_median_offline"] = float(np.median(archive["seconds"]))
result["note"] = "Question-disjoint development predictions. Realized-cost replay. No online readout cost measured."
(root/"summary.json").write_text(json.dumps(result,indent=2)+"\n")
print(json.dumps(result,indent=2))
