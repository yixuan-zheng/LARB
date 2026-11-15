"""Replay the frozen statistics from the published, graded draw summary."""
import json
from pathlib import Path
import sys

import numpy as np

from evaluate_full import evaluate, weights


def main():
    here = Path(__file__).resolve().parent
    data = json.loads((here/'scoring-input.json').read_text())
    cohort = json.loads((here/'cohort-v1.json').read_text())['selected']
    rows = data['rows']
    draws = np.asarray([r['draws'] for r in rows])
    assert draws.shape == (329,2,8,4)
    assert np.isin(draws[:,:,:,0],[0,1]).all()
    rates = draws[:,:,:,0].mean(axis=2)
    costs = draws[:,:,:,1:].mean(axis=2)
    scores = {}
    for name in ('prompt','mean_4k'):
        scores[name] = np.array([r['forecast'][name][1]-r['forecast'][name][0] for r in rows])
        np.testing.assert_array_equal(weights(scores[name]),[r['weights'][name] for r in rows])
    result = evaluate(rates,costs,scores,np.array([r['question'] for r in rows]),
                      sorted(r['id'] for r in cohort))
    result['collected_suffix_cost'] = dict(zip(('tokens','input_tokens','seconds'),
                                              (8*costs.sum(axis=(0,1))).tolist()))
    json.dump(result,sys.stdout,indent=2)
    print()


if __name__ == '__main__':
    main()
