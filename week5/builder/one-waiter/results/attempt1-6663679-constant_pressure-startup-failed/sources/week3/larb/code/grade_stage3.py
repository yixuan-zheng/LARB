"""Grade boxed answers, validate records, and retain parser issues for review."""
import argparse
from collections import Counter
import hashlib
import importlib.metadata
import json
from pathlib import Path
import re


def canonical(text):
    if text is None:
        return None
    text=text.replace('\\left','').replace('\\right','').replace('\\dfrac','\\frac').replace('\\tfrac','\\frac')
    text=re.sub(r'\\(?:text|mathrm|operatorname)\{([^{}]*)\}',r'\1',text)
    return ''.join(text.split()).strip('$')


def grade_answer(gold,pred):
    from math_verify import parse,verify,LatexExtractionConfig
    if pred is None:
        return dict(correct=False,method='missing_box',issue=None)
    if canonical(gold)==canonical(pred):
        return dict(correct=True,method='canonical_exact',issue=None)
    try:
        config=[LatexExtractionConfig(boxed_match_priority=0)]
        g=parse('$\\boxed{'+gold+'}$',extraction_config=config,raise_on_error=True)
        p=parse('$\\boxed{'+pred+'}$',extraction_config=config,raise_on_error=True)
        correct=bool(verify(g,p,timeout_seconds=3,raise_on_error=True))
        issue=None if g and p and any(not isinstance(x,str) for x in g) and any(not isinstance(x,str) for x in p) else 'string_fallback_or_empty_parse'
        return dict(correct=correct,method='math_verify',issue=issue,gold_parse=[str(x) for x in g],pred_parse=[str(x) for x in p])
    except Exception as exc:
        return dict(correct=False,method='math_verify_error',issue=type(exc).__name__+': '+str(exc))


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--root',required=True)
    p.add_argument('--allow-partial',action='store_true')
    args=p.parse_args()
    root=Path(args.root)
    protocol=json.loads((root/'protocol.json').read_text())
    problems=json.loads((root/'problems100.json').read_text())
    review_path=root/'manual-review.json'
    manual_entries=json.loads(review_path.read_text()) if review_path.exists() else []
    manual={(x['configuration'],x['index']):x for x in manual_entries}
    assert len(manual)==len(manual_entries)
    expected_hash=hashlib.sha256((root/'protocol.json').read_bytes()).hexdigest()
    rows=[]
    environments=set()
    source_sets=set()
    for task in sorted((root/'results').glob('task-*')):
        m=json.loads((task/'manifest.json').read_text())
        assert m['protocol_sha256']==expected_hash
        source_sets.add(tuple(sorted(m['source_hashes'].items())))
        if all(k in m for k in ['torch','transformers','cuda','gpu']):
            environments.add(tuple(m[k] for k in ['torch','transformers','cuda','gpu']))
        for name,h in m['source_hashes'].items():
            assert hashlib.sha256((task/('executed-'+name)).read_bytes()).hexdigest()==h
        if not args.allow_partial:
            assert m['completed'], task
        for file in sorted((task/'requests').glob('*.json')):
            r=json.loads(file.read_text())
            ids=r['token_ids']; config=m['configuration']
            assert r['configuration']==config['name'] and r['index'] in m['indices']
            assert r['reference']==str(problems[r['index']]['answer'])
            assert r['seed']==protocol['seed_base']+r['index']
            assert r['generated_tokens']==len(ids) and r['elapsed_seconds']>0
            boundary=r['thinking_tokens']
            if config['thinking'] and boundary is not None:
                assert ids[boundary]==m['close_id']
                assert boundary+1+r['answer_tokens']==len(ids)
            elif not config['thinking']:
                assert r['answer_tokens']==len(ids)
            assert r['answer_tokens']<=protocol['answer_cap']
            if r['forced_positions']:
                start=config['budget']; transition=m['transition_ids']
                assert r['forced_positions']==list(range(start,start+len(transition)))
                assert ids[start:start+len(transition)]==transition
                assert r['model_thinking_tokens']==config['budget']
            if config['name']=='full' and boundary is None:
                assert len(ids)<=protocol['full_thinking_safety_cap']
            if r['finish_reason']=='thinking_cap':
                assert config['name']=='full' and len(ids)==protocol['full_thinking_safety_cap']
            if r['finish_reason']=='answer_cap':
                assert r['answer_tokens']==protocol['answer_cap']
            result=grade_answer(r['reference'],r['extracted_answer'])
            correction=manual.get((r['configuration'],r['index']))
            if correction:
                assert hashlib.sha256(file.read_bytes()).hexdigest()==correction['record_sha256']
            correct=correction['correct'] if correction else result['correct']
            row={k:v for k,v in r.items() if k not in ['token_ids','rendered_prompt','raw_output','final_answer']}
            row.update(grading=result,manual_review=correction,boxed_correct=correct,completed_correct=correct and r['finish_reason']=='eos',record_path=str(file.relative_to(root)))
            rows.append(row)
    keys=[(r['configuration'],r['index']) for r in rows]
    assert len(keys)==len(set(keys))
    assert len(source_sets)<=1, 'Generation source differs across shards'
    assert len(environments)<=1, 'Runtime or GPU type differs across shards'
    if not args.allow_partial:
        assert len(rows)==600
        for c in protocol['configurations']:
            assert sorted(r['index'] for r in rows if r['configuration']==c['name'])==list(range(100))
    scores=root/'scores'
    scores.mkdir(exist_ok=True)
    (scores/'graded.json').write_text(json.dumps(rows,indent=2)+'\n')
    versions={name:importlib.metadata.version(name) for name in ['math-verify','latex2sympy2_extended','sympy','antlr4-python3-runtime','mpmath']}
    (scores/'grader-manifest.json').write_text(json.dumps(dict(versions=versions,environments=list(environments),protocol_sha256=expected_hash,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),manual_review_sha256=hashlib.sha256(review_path.read_bytes()).hexdigest() if review_path.exists() else None,records=len(rows),complete=len(rows)==600),indent=2)+'\n')
    review=[r for r in rows if r['grading']['issue'] or not r['boxed_correct'] or r['finish_reason']!='eos']
    (scores/'review-queue.json').write_text(json.dumps(review,indent=2)+'\n')
    for c in protocol['configurations']:
        group=[r for r in rows if r['configuration']==c['name']]
        print(c['name'],len(group),'completed-correct',sum(r['completed_correct'] for r in group),'boxed-correct',sum(r['boxed_correct'] for r in group),Counter(r['finish_reason'] for r in group))
    print('Review queue',len(review),'Grader issues',sum(bool(r['grading']['issue']) for r in rows))


if __name__=='__main__':
    main()
