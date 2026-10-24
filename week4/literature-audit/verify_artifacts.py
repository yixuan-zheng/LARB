"""Recompute published P-PAS+ comparisons from pinned public logs; no inference.

Download the files named in sources.json to an external cache first. This script
never imports or executes upstream benchmark code and never submits jobs.
"""
import argparse
import ast
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics

HERE = Path(__file__).resolve().parent

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def verify(cache):
    manifest = json.loads((HERE/'sources.json').read_text())
    results = []
    for model, candidate, baseline in [('qwen','ppas_plus_2k_768_s20','mbt_768_s20'),('nemotron','ppas_plus_16k_1280_s256','mbt_1280_s256')]:
        source = next(s for s in manifest['ppas_artifacts']['files'] if s.get('model')==model)
        path = cache/source['cache_filename']
        assert sha(path)==source['sha256'], 'Artifact hash mismatch'
        summaries, requests = [], []
        for line in path.read_text().splitlines():
            if line.startswith('REQUEST_RESULT:'):
                requests.append(ast.literal_eval(line.split(':',1)[1]))
            elif line.startswith('{'):
                try: row = ast.literal_eval(line)
                except (ValueError,SyntaxError): continue
                if 'avg_latency' in row: summaries.append(row)
        assert summaries and all(not r['failed'] and not r['error'] for r in summaries)
        configs = sorted({r['config_name'] for r in summaries})
        conditions = sorted({r['phase_schedule'] for r in summaries})
        cells = defaultdict(list)
        for row in summaries: cells[row['phase_schedule'],row['config_name']].append(row)
        comparisons = []
        for other in configs:
            if other==candidate: continue
            ratios = []
            for condition in conditions:
                a,b = cells[condition,candidate],cells[condition,other]
                assert {r['seed'] for r in a}=={r['seed'] for r in b}
                assert len({r['seed'] for r in a})==len(a)==len(b)
                ratios.append(statistics.mean(r['avg_latency'] for r in a)/statistics.mean(r['avg_latency'] for r in b))
            comparisons.append(dict(baseline=other,mean_latency_improvement_percent=100*(1-statistics.mean(ratios))))
        def indexed(config):
            data = [r for r in requests if r['config_name']==config]
            out = {(r['phase_schedule'],r['seed'],r['request_id']):r for r in data}
            assert len(data)==len(out)
            return out
        a,b = indexed(candidate),indexed(baseline)
        assert a.keys()==b.keys()
        for key in a:
            for field in ['scheduled_arrival_s','requested_prompt_tokens','requested_output_tokens']:
                assert a[key][field]==b[key][field], 'Unmatched logical request'
        faster = sum(a[k]['latency']<b[k]['latency'] for k in a)
        results.append(dict(model=model,summary_rows=len(summaries),conditions=len(conditions),seeds=sorted({r['seed'] for r in summaries}),all_logged_requests_succeeded=True,comparisons=comparisons,best_tested_static=baseline,matched_requests=len(a),candidate_faster=faster,candidate_faster_percent=100*faster/len(a),logical_arrivals_and_requested_lengths_match=True,sha256=source['sha256']))
    out=dict(scope='Arithmetic reproduction from author logs, not independent execution or model-quality validation.',aggregation='Paper Eq.10: average over six conditions of candidate/baseline ratios; each condition first averages its available seed runs.',results=results,documentation_gap='Appendix 10.5 states 11 seeds for each condition. Qwen artifact has seeds 0-9; Nemotron has 0-10. No missing Qwen seed inferred or fabricated.')
    (HERE/'verification.json').write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--artifact-dir',type=Path,required=True)
    verify(parser.parse_args().artifact_dir)
