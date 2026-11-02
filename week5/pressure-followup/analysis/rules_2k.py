"""Checkpoint-only routing features and the frozen eight-rule family."""
from collections import Counter
import re


def scalar_boxes(text):
    """Only complete scalar boxes in the observed prefix; no later text."""
    return re.findall(r'\\boxed\s*\{\s*(\d{1,3})\s*\}', text)


def features(token_ids, text):
    ids=tuple(token_ids)
    if len(ids)!=2048:
        raise ValueError('Expected exact 2048-token checkpoint')
    grams=[ids[i:i+4] for i in range(len(ids)-3)]
    counts=Counter(grams)
    # Fraction of occurrences beyond the first occurrence of each four-gram.
    repeat=(len(grams)-len(counts))/len(grams)
    suffix=grams[-253:]
    boxes=scalar_boxes(text)
    return dict(repeat_4gram_fraction=repeat,
                suffix_repeat_4gram_fraction=sum(counts[g]>1 for g in suffix)/len(suffix),
                boxed_scalar_count=len(boxes),
                stable_last_two_boxed_scalars=len(boxes)>=2 and boxes[-1]==boxes[-2])


def extend(rule,f):
    if rule=='no_box':
        return f['boxed_scalar_count']==0
    if rule=='no_stable_box':
        return not f['stable_last_two_boxed_scalars']
    threshold=float(rule.rsplit('_',1)[1])
    low=f['repeat_4gram_fraction']<threshold
    if rule.startswith('no_stable_box_low_repeat_'):
        return low and not f['stable_last_two_boxed_scalars']
    if rule.startswith('low_repeat_'):
        return low
    raise ValueError(rule)
