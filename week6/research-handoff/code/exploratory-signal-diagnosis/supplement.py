"""Add split checks, paid-readout diagnostics and input provenance."""
import hashlib
import json
import statistics
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'


def read(path):
    return json.loads(path.read_text())


def auc(positive,negative):
    return sum((a>b)+0.5*(a==b) for a in positive for b in negative)/len(positive)/len(negative)


def main():
    rows=read(ROOT/'graded-pairs.json')
    features=read(HERE/'features.json')
    summary=read(HERE/'summary.json')
    summary['original_split_tail_mean_auc_high']={}
    for split in ['calibration','evaluation']:
        positive=[x['tail_mean'] for x in features if x['original_split']==split and x['group']=='gain']
        negative=[x['tail_mean'] for x in features if x['original_split']==split and x['group']!='gain']
        summary['original_split_tail_mean_auc_high'][split]=auc(positive,negative)
    summary['answer_claim_presence']={
        group:dict(present=sum(x['explicit_answer_claims']>0 for x in features if x['group']==group),
                   total=sum(x['group']==group for x in features))
        for group in ['gain','already_correct','persistent_failure']}
    paid=[]
    cues=read(ROOT/'manifest.json')['cue_ids']
    feature_by_key={f['key']:f for f in features}
    for row in rows:
        if not row['eligible']:
            continue
        pair=read(ROOT/'pairs'/f"{row['key']}.json")
        call=read(ROOT/'calls'/f"{row['key']}-short.json")
        lp=call['sampled_logprobs'][len(cues):-1]
        assert pair['branches']['short']['token_ids'][4096:4096+len(cues)]==cues
        paid.append(dict(key=row['key'],group=feature_by_key[row['key']]['group'],
                         answer_mean=statistics.mean(lp),answer_last64=statistics.mean(lp[-64:])))
    summary['paid_readout']={}
    for metric in ['answer_mean','answer_last64']:
        positive=[x[metric] for x in paid if x['group']=='gain']
        negative=[x[metric] for x in paid if x['group']!='gain']
        summary['paid_readout'][metric]=dict(auc_gain_high=auc(positive,negative),
            medians={group:statistics.median(x[metric] for x in paid if x['group']==group)
                     for group in ['gain','already_correct','persistent_failure']})
    heldout=[r for r in rows if r['split']=='evaluation']
    extra_probe=sum(r['outcomes']['short']['tokens']-4096 for r in heldout
                    if not r['outcomes']['short']['correct'] and r['outcomes']['long']['correct'])
    oracle=read(ROOT/'decision.json')['oracle']['tokens']
    summary['paid_oracle_token_bound']=dict(free_oracle=oracle,extra_short_probe_tokens=extra_probe,
                                           total=oracle+extra_probe,fixed_long=346728)
    (HERE/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (HERE/'paid-readout.json').write_text(json.dumps(paid,indent=2)+'\n')
    paths=[ROOT/'graded-pairs.json',ROOT/'questions.json',ROOT/'calibration-seal.json']
    paths+=list((ROOT/'calls').glob('*-prefix.json'))
    paths+=list((ROOT/'calls').glob('*-short.json'))
    paths+=list((ROOT/'pairs').glob('q*.json'))
    lock={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(paths))}
    (HERE/'input-sha256.json').write_text(json.dumps(lock,indent=2)+'\n')


if __name__=='__main__':
    main()
