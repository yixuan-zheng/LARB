"""Paired descriptive comparison of a complete six-mode sweep."""
import argparse
import csv
import hashlib
import json
import platform
from pathlib import Path
import numpy as np


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',required=True);args=ap.parse_args()
    root=Path(args.root);protocol=json.loads((root/'protocol.json').read_text())
    rows=json.loads((root/'scores/graded.json').read_text())
    assert len(rows)==600
    rng=np.random.default_rng(622203)
    draws=rng.integers(0,100,size=(10000,100))
    groups={c['name']:sorted([r for r in rows if r['configuration']==c['name']],key=lambda r:r['index']) for c in protocol['configurations']}
    full=groups['full'];baseacc=np.array([r['completed_correct'] for r in full],dtype=float);basetime=np.array([r['elapsed_seconds'] for r in full])
    full_cap_count=sum(r['finish_reason']!='eos' for r in full)
    full_cap_optimistic_accuracy=float(baseacc.sum()+full_cap_count)
    summaries=[]
    for config in protocol['configurations']:
        name=config['name'];group=groups[name]
        assert [r['index'] for r in group]==list(range(100))
        correct=np.array([r['completed_correct'] for r in group],dtype=float)
        times=np.array([r['elapsed_seconds'] for r in group])
        delta=(correct-baseacc)*100
        boot_delta=delta[draws].mean(axis=1)
        boot_time=np.median(times[draws],axis=1)/np.median(basetime[draws],axis=1)
        low,high=np.percentile(boot_delta,[2.5,97.5])
        time_low,time_high=np.percentile(boot_time,[2.5,97.5])
        reduction=1-float(np.median(times)/np.median(basetime))
        summary=dict(configuration=name,completed_correct=int(correct.sum()),accuracy_pct=float(correct.mean()*100),
            boxed_correct=sum(r['boxed_correct'] for r in group),normal_completions=sum(r['finish_reason']=='eos' for r in group),
            thinking_cap_hits=sum(r['finish_reason']=='thinking_cap' for r in group),answer_cap_hits=sum(r['finish_reason']=='answer_cap' for r in group),
            missing_boxes=sum(r['extracted_answer'] is None for r in group),
            reopened_thinking=sum(r['thinking_reopened'] for r in group),
            automated_completed_correct=sum(r['grading']['correct'] and r['finish_reason']=='eos' for r in group),
            manual_corrections=[r['index'] for r in group if r.get('manual_review')],
            median_seconds=float(np.median(times)),mean_seconds=float(times.mean()),p95_seconds=float(np.percentile(times,95)),total_seconds=float(times.sum()),
            median_model_thinking_tokens=float(np.median([r['model_thinking_tokens'] for r in group])),
            accuracy_delta_pp=float(delta.mean()),accuracy_delta_ci95=[float(low),float(high)],
            median_time_reduction_pct=100*reduction,median_time_ratio_ci95=[float(time_low),float(time_high)],
            full_correct_candidate_wrong=int(((baseacc==1)&(correct==0)).sum()),full_wrong_candidate_correct=int(((baseacc==0)&(correct==1)).sum()),
            full_accuracy_if_all_cap_failures_rescued_pct=full_cap_optimistic_accuracy,
            accuracy_delta_vs_optimistic_full_pp=float(correct.sum()-full_cap_optimistic_accuracy),
            point_screen_pass=(name!='full' and float(delta.mean())>=-3.00000001 and reduction>=0.25))
        summaries.append(summary)
    out=root/'analysis';out.mkdir(exist_ok=True)
    (out/'summary.json').write_text(json.dumps(summaries,indent=2)+'\n')
    with (out/'summary.csv').open('w') as f:
        w=csv.DictWriter(f,fieldnames=list(summaries[0]));w.writeheader();w.writerows(summaries)
    with (out/'per-problem.csv').open('w') as f:
        fields=['configuration','index','reference','raw_extracted_answer','reviewed_answer','automated_correct','completed_correct','boxed_correct','finish_reason','elapsed_seconds','model_thinking_tokens','manual_review_reason','record_path']
        writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader()
        for r in rows:
            review=r.get('manual_review')
            writer.writerow(dict(configuration=r['configuration'],index=r['index'],reference=r['reference'],raw_extracted_answer=r['extracted_answer'],reviewed_answer=review['reviewed_answer'] if review else r['extracted_answer'],automated_correct=r['grading']['correct'],completed_correct=r['completed_correct'],boxed_correct=r['boxed_correct'],finish_reason=r['finish_reason'],elapsed_seconds=r['elapsed_seconds'],model_thinking_tokens=r['model_thinking_tokens'],manual_review_reason=review['reason'] if review else '',record_path=r['record_path']))
    # Check that the changed behavior begins only at the specified boundary.
    prefix=[]
    for config in protocol['configurations']:
        if not config['budget']: continue
        for r in groups[config['name']]:
            f=json.loads((root/r['record_path']).read_text())
            b=json.loads((root/full[r['index']]['record_path']).read_text())
            n=config['budget'] if f['forced_positions'] else (f['thinking_tokens'] or len(f['token_ids']))
            prefix.append(dict(configuration=config['name'],index=r['index'],tokens_compared=n,match=f['token_ids'][:n]==b['token_ids'][:n]))
    (out/'prefix-checks.json').write_text(json.dumps(prefix,indent=2)+'\n')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    (out/'analysis-manifest.json').write_text(json.dumps(dict(python=platform.python_version(),numpy=np.__version__,matplotlib=matplotlib.__version__,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),graded_sha256=hashlib.sha256((root/'scores/graded.json').read_bytes()).hexdigest(),bootstrap_draws=10000,bootstrap_seed=622203),indent=2)+'\n')
    fig,ax=plt.subplots(figsize=(8.3,5.3))
    for s in summaries:
        x,y=s['median_seconds'],s['accuracy_pct']
        ax.scatter(x,y,s=65)
        offset=(7,-16) if s['configuration']=='budget-512' else (7,7)
        ax.annotate(s['configuration'],(x,y),xytext=offset,textcoords='offset points',fontsize=9)
    ref=summaries[0]
    ax.axhline(ref['accuracy_pct']-3,color='gray',ls='--',lw=1,label='Full accuracy minus 3 pp')
    ax.axvline(ref['median_seconds']*.75,color='gray',ls=':',lw=1,label='25% below full median time')
    ax.set(xlabel='Median request runtime (seconds; cap hits included)',ylabel='Correct, normally completed answers (%)',title='Qwen3-4B: 100 fixed MATH-500 development problems')
    ax.grid(alpha=.2);ax.legend(loc='best',fontsize=8)
    fig.tight_layout();fig.savefig(out/'accuracy-time.png',dpi=180);fig.savefig(out/'accuracy-time.pdf');plt.close(fig)
    print(json.dumps(summaries,indent=2))
    print('Prefix matches:',sum(r['match'] for r in prefix),'/',len(prefix))


if __name__=='__main__':main()
