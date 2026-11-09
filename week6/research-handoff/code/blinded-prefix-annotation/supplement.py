"""Post-join descriptive accounting. Does not define or execute a controller."""
import json
from collections import Counter, defaultdict
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'


def read(path):
    return json.loads(path.read_text())


def main():
    joined=read(HERE/'joined-annotations.json')
    graded=read(ROOT/'graded-pairs.json')
    by_key={r['key']:r for r in joined}
    categories={}
    for label in ['A','B','C','U']:
        group=[r for r in joined if r['label_a']==r['label_b']==label]
        categories[label]=dict(instances=len(group),gains=sum(r['gain'] for r in group),
            short_correct=sum(r['short_correct'] for r in group),
            persistent_failure=sum(not r['short_correct'] and not r['long_correct'] for r in group))
    question_rows=defaultdict(list)
    for row in joined:
        question_rows[row['question_id']].append(row)
    pairs=[r for r in question_rows.values() if len(r)==2]
    label_variation={}
    for field in ['label_a','label_b','consensus_b']:
        label_variation[field]=dict(paired_questions=len(pairs),
            same_across_seed=sum(r[0][field]==r[1][field] for r in pairs))
    accounting={}
    for split in ['calibration','evaluation','all']:
        items=[r for r in graded if split=='all' or r['split']==split]
        totals=dict(instances=len(items),correct=0,tokens=0,long_correct=0,long_tokens=0)
        for row in items:
            selected='long' if by_key.get(row['key'],{}).get('consensus_b',False) else 'short'
            totals['correct']+=row['outcomes'][selected]['correct']
            totals['tokens']+=row['outcomes'][selected]['tokens']
            totals['long_correct']+=row['outcomes']['long']['correct']
            totals['long_tokens']+=row['outcomes']['long']['tokens']
        totals['token_saving_vs_long']=1-totals['tokens']/totals['long_tokens']
        accounting[split]=totals
    result=dict(consensus_categories=categories,within_question_label_variation=label_variation,
        posthoc_token_accounting=accounting,
        note='Accounting uses labels to sum existing branch records. It excludes annotation cost and has no fresh validation or concurrency.')
    (HERE/'SUPPLEMENT.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
