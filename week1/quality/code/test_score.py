"""CPU checks for answer extraction and the paired statistics in score.py."""
import re

import numpy as np

from common import MANIFESTS
from score import extract, is_correct, mcnemar, paired_bootstrap, wilson

# the 8 few-shot answers must extract to their own final number
for answer in re.findall(r"A: (.*)", (MANIFESTS / "fewshot_prompt.txt").read_text()):
    assert extract(answer) == re.search(r"The answer is (\d+)", answer).group(1), answer

cases = {
    "So 3 + 4 = 7. The answer is 7.\n\n": "7",
    "Total is 1,000 + 250 = 1,250. The answer is 1,250.": "1250",
    "She pays $18.50 in total. The answer is $18.50.": "18.50",
    "The temperature drops to -5 degrees. The answer is -5.": "-5",
    "First 2 + 2 = 4, then 4 * 3 = 12": "12",  # no "The answer is": last number
    "The answer is 5. The answer is 6.": "6",  # last occurrence wins
    "The answer is 9.\n\nQ: Tom has 3 apples": "9",  # text after a stop string is ignored
    "I am not sure.": None,
}
for text, expected in cases.items():
    assert extract(text) == expected, (text, extract(text))
assert is_correct("18.50", "18.5") and is_correct("1250", "1250") and not is_correct(None, "3")

lo, hi = wilson(40, 100)
assert abs(lo - 0.3094) < 1e-3 and abs(hi - 0.4980) < 1e-3

# 10 examples only static_L gets right, 2 only the schedule gets right:
# p = 2 * (C(12,0) + C(12,1) + C(12,2)) / 2^12
ref = np.array([1] * 10 + [0] * 2 + [1] * 30 + [0] * 58, dtype=float)
sched = np.array([0] * 10 + [1] * 2 + [1] * 30 + [0] * 58, dtype=float)
p, ref_only, sched_only = mcnemar(ref, sched)
assert (ref_only, sched_only) == (10, 2) and abs(p - 2 * 79 / 4096) < 1e-12

lo, hi = paired_bootstrap(sched, ref)
assert lo < -8.0 < hi and hi < 0, (lo, hi)  # true difference is -8 pp
assert paired_bootstrap(ref, ref) == (0.0, 0.0)  # identical outcomes have zero paired spread
print("PASS: extraction and statistics")
