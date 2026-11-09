"""Exploratory CPU features from saved prefixes; no inference or controller."""
import csv
import hashlib
import json
import math
import re
import statistics
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'


def read(path):
    return json.loads(path.read_text())


def mean(values):
    return statistics.mean(values) if values else 0.


def auc(positive,negative):
    if not positive or not negative:
        return None
    return sum((a>b)+0.5*(a==b) for a in positive for b in negative)/(len(positive)*len(negative))


def word_count(pattern,text):
    return len(re.findall(pattern,text,re.I))


def features(call):
    ids=call['token_ids']; lp=call['sampled_logprobs']
    text=call['raw_output'];tail=text[-5000:]
    grams=[tuple(ids[i:i+4]) for i in range(max(0,len(ids)-1024),len(ids)-3)]
    windows=[mean(lp[i:i+256]) for i in range(len(lp)-1024,len(lp),256)]
    prior=text[:-5000].casefold()
    math_lines=[re.sub(r'\s+','',line.casefold()) for line in tail.splitlines()
                if '=' in line and len(line.strip())>6]
    correction=r"\b(?:wait|however|mistake|incorrect|reconsider|instead|actually|doesn't match)\b"
    verification=r"\b(?:verify|verification|check|checking|confirm|double.check)\b"
    return dict(tail_mean=mean(lp[-256:]),prefix_mean=mean(lp),
        confidence_change=mean(lp[-1024:])-mean(lp[-2048:-1024]),
        worst_recent_window=min(windows),
        lowprob_fraction=sum(x<math.log(0.1) for x in lp[-1024:])/1024,
        repetition4=1-len(set(grams))/len(grams),
        repeated_equation_fraction=mean([line in re.sub(r'\s+','',prior) for line in math_lines]),
        correction_markers=word_count(correction,tail),
        verification_markers=word_count(verification,tail),
        boxed_candidates=tail.count('\\boxed'),
        explicit_answer_claims=len(re.findall(r'(?:final answer|the answer|remainder)\s*(?:is|=|:)\s*(?:\$\s*)?(\d{1,5})',text,re.I)),
        recent_math_lines=len(set(math_lines)))


def main():
    graded=read(ROOT/'graded-pairs.json')
    questions={q['id']:q for q in read(ROOT/'questions.json')}
    rows=[]
    excerpts=[]
    for row in graded:
        if not row['eligible']:
            continue
        pair=read(ROOT/'pairs'/f"{row['key']}.json")
        call=read(ROOT/'calls'/f"{row['key']}-prefix.json")
        assert pair['prefix_token_ids']==call['token_ids']
        assert pair['prefix_hash']==hashlib.sha256(json.dumps(call['token_ids'],separators=(',',':')).encode()).hexdigest()
        short,long=[row['outcomes'][b] for b in ['short','long']]
        group='gain' if not short['correct'] and long['correct'] else 'already_correct' if short['correct'] else 'persistent_failure'
        data=dict(key=row['key'],question=questions[row['id']]['stable_id'],id=row['id'],
                  original_split=row['split'],block=row['block'],group=group,**features(call))
        rows.append(data)
        extension=pair['branches']['long']['raw_output']
        # Full text copies are for manual diagnosis only; never used by features.
        excerpts.append(dict(key=row['key'],question=data['question'],group=group,
            question_text=questions[row['id']]['problem'],
            prefix_head=call['raw_output'][:700],prefix_tail=call['raw_output'][-3500:],
            short_answer=pair['branches']['short']['raw_output'].split('</think>')[-1][-1400:],
            long_continuation=extension[len(call['raw_output']):][:3500],
            long_answer=extension.split('</think>')[-1][-1400:]))
    signals=list(features(read(ROOT/'calls'/f"{rows[0]['key']}-prefix.json")))
    summary={}
    for name in signals:
        groups={g:[r[name] for r in rows if r['group']==g]
                for g in ['gain','already_correct','persistent_failure']}
        # Within-question contrasts use only questions with a gain in one seed.
        contrasts=[]
        for r in rows:
            if r['group']!='gain':
                continue
            for other in rows:
                if other['id']==r['id'] and other['block']!=r['block'] and other['group']!='gain':
                    contrasts.append(r[name]-other[name])
        summary[name]=dict(medians={g:statistics.median(v) for g,v in groups.items()},
            auc_gain_vs_other_high=auc(groups['gain'],groups['already_correct']+groups['persistent_failure']),
            auc_gain_vs_persistent_failure_high=auc(groups['gain'],groups['persistent_failure']),
            within_question_deltas=contrasts,
            within_question_positive=sum(x>0 for x in contrasts),
            within_question_negative=sum(x<0 for x in contrasts))
    (HERE/'features.json').write_text(json.dumps(rows,indent=2)+'\n')
    (HERE/'summary.json').write_text(json.dumps(dict(groups=dict(Counter(r['group'] for r in rows)),
        features=summary),indent=2)+'\n')
    (HERE/'trace-excerpts.json').write_text(json.dumps(excerpts,indent=2,ensure_ascii=False)+'\n')
    with (HERE/'features.csv').open('w',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    for name,s in summary.items():
        print(name, 'medians',s['medians'],'AUC',round(s['auc_gain_vs_other_high'],3),
              'wrong-only',round(s['auc_gain_vs_persistent_failure_high'],3),
              'within',s['within_question_positive'],s['within_question_negative'])


if __name__=='__main__':
    main()
