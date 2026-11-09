"""Join sealed independent annotations to outcomes and apply the frozen gates."""
import csv
import hashlib
import json
import math
import random
from collections import Counter
from pathlib import Path

HERE=Path(__file__).resolve().parent
ROOT=HERE.parent/'shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'
LABELS=['A','B','C','U']


def read(path):
    return json.loads(path.read_text())


def kappa(first,second):
    count=len(first)
    observed=sum(a==b for a,b in zip(first,second))/count
    a,b=Counter(first),Counter(second)
    expected=sum(a[label]*b[label] for label in LABELS)/(count*count)
    value=(observed-expected)/(1-expected) if expected<1 else None
    return dict(kappa=value,observed_agreement=observed,expected_agreement=expected,
                first_counts=dict(a),second_counts=dict(b))


def selected_metrics(rows,selected):
    positives=[r for r in rows if r['gain']]
    group=[r for r in rows if r['key'] in selected]
    captured=[r for r in group if r['gain']]
    rate=len(captured)/len(group) if group else None
    base=len(positives)/len(rows)
    return dict(selected=len(group),gains_captured=len(captured),
                distinct_gain_questions=len({r['question_id'] for r in captured}),
                gain_prevalence=rate,base_prevalence=base,
                enrichment=rate/base if rate is not None and base else None,
                captured_keys=[r['key'] for r in captured])


def main():
    plan=read(HERE/'PLAN.json')
    seal=read(HERE/'reader-seal.json')
    mapping=read(HERE/'private-mapping.json')
    annotations={}
    frozen=read(HERE/'freeze-sha256.json')
    for reader in ['reader-a','reader-b']:
        path=HERE/reader/'annotations.jsonl'
        assert hashlib.sha256(path.read_bytes()).hexdigest()==seal[reader]['annotations_sha256']
        entries=[json.loads(line) for line in path.read_text().splitlines() if line.strip()]
        assert len(entries)==57 and len({e['case_id'] for e in entries})==57
        data={}
        for entry in entries:
            assert entry['label'] in LABELS
            for field in ['evidence','remaining_obligation','reason','confidence']:
                assert isinstance(entry[field],str) and entry[field].strip()
            assert entry['confidence'] in ['high','medium','low']
            packet_path=HERE/reader/'cases'/f"{entry['case_id']}.json"
            original_path=Path(plan['packet_roots'][reader])/'cases'/packet_path.name
            assert hashlib.sha256(packet_path.read_bytes()).hexdigest()==frozen[str(original_path)]
            packet=read(packet_path)
            assert entry['evidence'] in packet['prefix'],(reader,entry['case_id'],'quote mismatch')
            assert len(entry['evidence'])<=300
            data[mapping[reader][entry['case_id']]]=entry
        annotations[reader]=data
    graded=read(ROOT/'graded-pairs.json')
    eligible=sorted([r for r in graded if r['eligible']],key=lambda x:x['key'])
    assert len(eligible)==57
    rows=[]
    for item in eligible:
        short,long=(item['outcomes'][branch]['correct'] for branch in ['short','long'])
        a=annotations['reader-a'][item['key']]
        b=annotations['reader-b'][item['key']]
        rows.append(dict(key=item['key'],question_id=item['id'],block=item['block'],
            original_split=item['split'],score=item['score'],
            gain=not short and long,short_correct=short,long_correct=long,
            label_a=a['label'],label_b=b['label'],
            consensus_b=a['label']==b['label']=='B',
            evidence_a=a['evidence'],evidence_b=b['evidence'],
            obligation_a=a['remaining_obligation'],obligation_b=b['remaining_obligation']))
    first=[r['label_a'] for r in rows];second=[r['label_b'] for r in rows]
    agreement=kappa(first,second)
    binary=kappa(['B' if x=='B' else 'A' for x in first],
                 ['B' if x=='B' else 'A' for x in second])
    selected={r['key'] for r in rows if r['consensus_b']}
    primary=selected_metrics(rows,selected)
    readers={name:selected_metrics(rows,{r['key'] for r in rows if r[field]=='B'})
             for name,field in [('reader-a','label_a'),('reader-b','label_b')]}
    failures=[]
    if agreement['kappa'] is None or agreement['kappa']<0.6:
        failures.append('four-category kappa below 0.6 or undefined')
    if primary['enrichment'] is None or primary['enrichment']<2:
        failures.append('consensus unfinished-route gain enrichment below 2')
    if primary['gains_captured']<4:
        failures.append('fewer than four gains captured')
    if primary['distinct_gain_questions']<3:
        failures.append('gains captured on fewer than three questions')
    ids=sorted({r['question_id'] for r in rows})
    by_question={i:[r for r in rows if r['question_id']==i] for i in ids}
    rng=random.Random(107222)
    bootstrap=[]
    for _ in range(10000):
        sample=[r for i in rng.choices(ids,k=len(ids)) for r in by_question[i]]
        effect=selected_metrics(sample,selected)['enrichment']
        if effect is not None and math.isfinite(effect):
            bootstrap.append(effect)
    bootstrap.sort()
    interval=[bootstrap[int((len(bootstrap)-1)*p)] for p in [0.025,0.975]] if bootstrap else None
    decision='stop' if failures else 'inconclusive'
    if not failures and interval is not None and interval[0]>1 and len(bootstrap)>=9500:
        decision='earn_practical_signal_feasibility_review'
    bands=[]
    ordered=sorted(rows,key=lambda r:(r['score'],r['key']))
    for index in range(3):
        band=ordered[index*19:(index+1)*19]
        bands.append(dict(band=index+1,score_min=band[0]['score'],score_max=band[-1]['score'],
                          consensus=selected_metrics(band,selected)))
    discordant=[]
    for question,items in by_question.items():
        if len(items)==2 and sum(r['gain'] for r in items)==1:
            discordant.append(dict(question_id=question,
                                   rows=[{k:r[k] for k in ['key','gain','label_a','label_b','score']} for r in items]))
    confusion={a:{b:sum(r['label_a']==a and r['label_b']==b for r in rows) for b in LABELS} for a in LABELS}
    result=dict(decision=decision,failures=failures,agreement=agreement,binary_b_agreement=binary,
        confusion=confusion,primary=primary,readers=readers,
        bootstrap_enrichment_ci95=interval,valid_bootstrap_replicates=len(bootstrap),
        score_bands=bands,discordant_seed_questions=discordant,
        original_splits={split:selected_metrics([r for r in rows if r['original_split']==split],selected)
                         for split in ['calibration','evaluation']},
        methodology='Two outcome-blinded AI sessions of same model family. Procedural blinding, not OS access isolation. No human-reader claim.')
    (HERE/'RESULTS.json').write_text(json.dumps(result,indent=2)+'\n')
    (HERE/'joined-annotations.json').write_text(json.dumps(rows,indent=2)+'\n')
    with (HERE/'joined-annotations.csv').open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]))
        writer.writeheader();writer.writerows(rows)
    print(json.dumps(result,indent=2))


if __name__=='__main__':
    main()
