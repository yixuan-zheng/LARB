"""CPU-only correctness evaluation after feature hashes and labels are checked."""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

import numpy as np
import sklearn
from sklearn.decomposition import PCA
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.model_selection import GroupKFold

from prepare import HERE, REPO, RUNS, read, token_hash

sys.path.insert(0,str(REPO/'week6/aime-budget-screen'))
from common import extract_integer


def evaluation(x, y, groups, config):
    pred = np.zeros((x.shape[1], len(y)))
    folds = list(GroupKFold(config['folds'], shuffle=True, random_state=config['seed']).split(x,y,groups))
    for train,test in folds:
        assert not set(groups[train]) & set(groups[test])
        assert len(np.unique(y[train])) == 2
        for j in range(x.shape[1]):
            pca = PCA(n_components=min(config['pca_max'], x.shape[2], len(train)-1),random_state=config['seed'])
            z = pca.fit_transform(x[train,j])
            probe = LogisticRegression(C=1,solver='liblinear',max_iter=1000,class_weight='balanced',
                                       random_state=config['seed']).fit(z,y[train])
            pred[j,test] = probe.predict_proba(pca.transform(x[test,j]))[:,1]
    return pred


def archive():
    rows = {}
    for cohort,root in RUNS.items():
        questions = {q['id']:q for q in read(root/'questions.json')}
        for task in read(root/'schedule.json'):
            pair = read(root/'pairs'/f"{task['key']}.json")
            if not pair['eligible']:
                continue
            q = questions[task['id']]
            long = pair['branches']['long']
            label = int(long['normal'] and extract_integer(long['raw_output'])['value']==q['answer'])
            group = re.sub(r'[\s$\\{}]', '',unicodedata.normalize('NFKC',q['problem']).casefold())
            rows[f"{cohort}:{task['key']}"] = (group,label,token_hash(pair['prompt_token_ids']+pair['prefix_token_ids']))
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    for name,digest in read(HERE/'evaluation-lock.json').items():
        assert hashlib.sha256((HERE/name).read_bytes()).hexdigest()==digest,name
    config = read(HERE/'config.json')
    assert sklearn.__version__ == config['sklearn']
    status = read(args.run/'status.json')
    assert status['complete'] and status['rows']==115 and read(args.run/'engineering-gate.json')['passed']
    assert read(args.run/'manifest.json')['config']==config
    path=args.run/'features.npz'
    assert hashlib.sha256(path.read_bytes()).hexdigest()==status['feature_sha256']
    data=np.load(path,allow_pickle=False)
    x,keys=data['X'],data['keys']
    rows=archive()
    assert len(set(keys)) == len(keys) == len(rows) == 115 and set(keys)==set(rows)
    assert np.array_equal(data['hashes'],[rows[k][2] for k in keys])
    checkpoints = data['checkpoints'].tolist()
    assert checkpoints == read(args.run/'engineering-gate.json')['checkpoints']
    assert checkpoints in ([0, 4096], config['checkpoints'])
    assert x.shape[:2] == (115,len(checkpoints)+1) and np.isfinite(x).all()
    y=np.array([rows[k][1] for k in keys])
    groups=np.array([rows[k][0] for k in keys])
    pred=evaluation(x,y,groups,config)
    names=[str(t) for t in checkpoints]+['4096_last_token']
    metrics={name:dict(auc=float(roc_auc_score(y,p)),accuracy=float(np.mean((p>.5)==y)),
                       brier=float(np.mean((p-y)**2))) for name,p in zip(names,pred)}
    indices=[np.flatnonzero(groups==group) for group in np.unique(groups)]
    rng=np.random.default_rng(config['seed'])
    deltas={t:[] for t in ('4','4096') if t in names}
    for _ in range(config['bootstrap']):
        ix=np.concatenate([indices[i] for i in rng.integers(len(indices),size=len(indices))])
        if np.unique(y[ix]).size < 2:
            continue
        baseline=roc_auc_score(y[ix],pred[0,ix])
        for t,values in deltas.items():
            values.append(roc_auc_score(y[ix],pred[names.index(t),ix])-baseline)
    p=pred[names.index('4096')]
    misses={str(label):[dict(key=str(keys[i]),probability=float(p[i])) for i in
                       sorted(np.flatnonzero((y==label)&((p>.5)!=y)),key=lambda i:-abs(p[i]-.5))[:3]]
            for label in (0,1)}
    cohorts={cohort:dict(rows=sum(k.startswith(cohort+':') for k in keys),
                         correct=sum(int(v) for k,v in zip(keys,y) if k.startswith(cohort+':')))
             for cohort in RUNS}
    result=dict(metrics=metrics,cohorts=cohorts,questions=len(indices),positive_rate=float(y.mean()),
                auc_lift_95={t:np.quantile(v,[.025,.975]).tolist() for t,v in deltas.items()},
                highest_confidence_misses=misses)
    with args.output.open('x') as handle:
        json.dump(result,handle,indent=2)
        handle.write('\n')


if __name__=='__main__':
    main()
