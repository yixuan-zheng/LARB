"""Recheck saved campaign grades and derive descriptive paired comparisons; no inference."""
import gzip
import hashlib
import json
from pathlib import Path
from analyze import grade

HERE = Path(__file__).resolve().parent

def sha(data):
    return hashlib.sha256(data).hexdigest()

def assess():
    evidence = []
    aggregate = json.loads((HERE/'analysis/summary.json').read_text())
    for job in ['6512259', '6512260']:
        root = HERE/'results'/('job-'+job)
        saved = {name: (root/'analysis'/name).read_bytes() for name in ['summary.json', 'graded.json', 'review-queue.json']}
        storage = json.loads((root/'storage-manifest.json').read_text())['scheduler.jsonl']
        assert sha((root/'scheduler.jsonl.gz').read_bytes()) == storage['gzip_sha256']
        assert sha(gzip.decompress((root/'scheduler.jsonl.gz').read_bytes())) == storage['raw_sha256']
        try:
            summary = grade(root)
            assert all((root/'analysis'/name).read_bytes() == data for name, data in saved.items()), 'Local grading differs from cluster grading'
        finally:
            for name, data in saved.items(): (root/'analysis'/name).write_bytes(data)
        assert next(r['summary'] for r in aggregate['results'] if r['job']==job) == summary
        rows = json.loads(saved['graded.json'])
        paired = []
        for baseline in ['fixed2048','fixed4096','admission']:
            for block in [0,1]:
                pairs = [(next(r for r in rows if r['policy']==baseline and r['block']==block and r['index']==i), next(r for r in rows if r['policy']=='live' and r['block']==block and r['index']==i)) for i in sorted({r['index'] for r in rows})]
                paired.append(dict(baseline=baseline,block=block,on_time_gains=[a['index'] for a,l in pairs if l['correct_on_time'] and not a['correct_on_time']],on_time_losses=[a['index'] for a,l in pairs if a['correct_on_time'] and not l['correct_on_time']],accuracy_gains=[a['index'] for a,l in pairs if l['completed_correct'] and not a['completed_correct']],accuracy_losses=[a['index'] for a,l in pairs if a['completed_correct'] and not l['completed_correct']]))
        evidence.append(dict(job=job,condition=summary['condition'],raw_requests=len(list((root/'requests').glob('*.json'))),local_regrade_matches_cluster=True,archive_hashes_verified=True,analysis_sha256={name:sha(data) for name,data in saved.items()},paired=paired,blocks=[dict(block=b,policy=p,on_time=sum(r['correct_on_time'] for r in rows if r['block']==b and r['policy']==p),eventual=sum(r['completed_correct'] for r in rows if r['block']==b and r['policy']==p)) for b in [0,1] for p in ['fixed2048','fixed4096','admission','live']]))
    assert aggregate['complete'] and not aggregate['errors'] and sum(r['raw_requests']-2 for r in evidence)==192
    result=dict(verified=True,measured_outcomes=192,unique_questions=12,jobs=evidence,note='Descriptive repeated development questions, not independent population trials. Original cluster analysis bytes preserved.')
    (HERE/'analysis/assessment.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))

if __name__=='__main__': assess()
