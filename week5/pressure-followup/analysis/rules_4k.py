"""Frozen 4K observable rule family; no final outcomes enter these functions."""
from collections import Counter
import re
BOX=re.compile(r'\\boxed\s*\{\s*(\d{1,3})\s*\}')
CANDIDATE=re.compile(r'\b(?:answer|result)\s*(?:(?:is|equals)\s*|:\s*)\$?\s*(\d{1,3})(?!\d)',re.I)
CORRECTION=re.compile(r'\b(?:wait|mistake|incorrect|contradiction|recalculate|reconsider)\b',re.I)
def features(ids,text):
    if len(ids)!=4096:raise ValueError('Expected4096token prefix')
    ids=tuple(ids);grams=[ids[i:i+4] for i in range(len(ids)-3)];counts=Counter(grams);suffix=grams[-253:]
    boxes=BOX.findall(text);candidates=CANDIDATE.findall(text)
    return dict(box_count=len(boxes),candidate_count=len(candidates)+len(boxes),recent_correction=bool(CORRECTION.search(text[-2048:])),suffix_repeat_fraction=sum(counts[g]>1 for g in suffix)/len(suffix))
def extend(rule,f):
    if rule=='fixed4k':return False
    if rule=='no_box':return f['box_count']==0
    if rule=='no_candidate':return f['candidate_count']==0
    if rule=='recent_correction':return f['recent_correction']
    if rule=='no_candidate_or_recent_correction':return f['candidate_count']==0 or f['recent_correction']
    if rule.startswith('low_suffix_repeat_'):return f['suffix_repeat_fraction']<float(rule.rsplit('_',1)[1])
    if rule=='no_candidate_low_suffix_repeat_0.5':return f['candidate_count']==0 and f['suffix_repeat_fraction']<.5
    raise ValueError(rule)
