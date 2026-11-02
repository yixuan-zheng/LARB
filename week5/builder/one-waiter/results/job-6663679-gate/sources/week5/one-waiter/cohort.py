"""Published cohort rule: rank exposed 0-99 questions by SHA-256, never by outcomes."""
import hashlib
import json
from pathlib import Path

SALT = 'week5-one-waiter-v1'
# Indices already used by Week 3/4: the 12-question fixed-control cohort, the
# 1/4/5 mechanics gate, and the 0/2 per-job calibration pair.
USED = (0, 1, 2, 4, 5, 10, 12, 28, 42, 65, 76, 77, 83, 89, 94, 98)


def rank(index):
    return hashlib.sha256(f'{SALT}:{index}'.encode()).hexdigest()


def cohort(size=24, pool=range(100), used=USED):
    remaining = [i for i in pool if i not in used]
    return sorted(remaining, key=lambda i: (rank(i), i))[:size]


if __name__ == '__main__':
    ids = cohort()
    out = dict(salt=SALT, used_indices=list(USED), remaining_pool=sorted(set(range(100)) - set(USED)),
               cohort_rank_order=ids, ranks={i: rank(i) for i in ids})
    Path(__file__).with_name('cohort.json').write_text(json.dumps(out, indent=2) + '\n')
    print(json.dumps(ids))
