"""Verify the archived allocation decomposition using only standard Python."""
from collections import defaultdict
import json
import math
from pathlib import Path


def main():
    path = Path(__file__).with_name('mlp-decomposition.json')
    for split, data in json.loads(path.read_text()).items():
        groups = defaultdict(list)
        spends = {name: [] for name in ('linear', 'mlp')}
        for row in data['rows']:
            groups[row['question']].append(row)
            for name in spends:
                spends[name].append(row['weights'][name])
        assert all(math.isclose(sum(w),164) for w in spends.values())
        between = within = 0.0
        for rows in groups.values():
            avg = sum(r['benefit'] for r in rows)/len(rows)
            for row in rows:
                assert math.isclose(avg,row['question_mean'],abs_tol=1e-12)
                change = row['weights']['mlp']-row['weights']['linear']
                between += change*avg
                within += change*(row['benefit']-avg)
        for key, actual in [('between',between),('within',within),('total',between+within)]:
            if not math.isclose(actual,data[key],abs_tol=1e-12):
                raise ValueError(f'{split} {key} does not match')
        print(f'{split}: {between:+.3f} between, {within:+.3f} within, {between+within:+.3f} total')


if __name__ == '__main__':
    main()
