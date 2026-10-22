"""Exercise the extended audit on real development records and deliberate corruptions."""
import copy
import gzip
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from execution import digest,trace_for
from validate import validate

REPO=Path(__file__).resolve().parents[2]
SOURCE=REPO/'week4/step1/controlled-comparison/results/job-6440653'

def write(root,name,data):
    (root/name).write_text(json.dumps(data,indent=2)+'\n')

class AuditRegression(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();root=cls.root=Path(cls.tmp.name)
        plan=json.loads((REPO/'week4/evaluation-plan/plan.json').read_text())
        plan['sample']['shards'][0]=dict(shard=0,indices=list(range(12)),block_positions=[list(range(12))]*2)
        write(root,'plan.json',plan)
        old=json.loads((SOURCE/'run-complete.json').read_text())
        phases=[p for p in old['phases'] if p['policy'] in ['admission','live'] or p['block'] is None]
        keys={r['key'] for p in phases for r in p['client']}
        trace=trace_for(plan,0,'late_burst',phases[0],phases[1]['epoch']-1)
        write(root,'trace.json',trace)
        write(root,'trace-freeze.json',dict(sha256=digest(root/'trace.json'),plan_sha256=digest(root/'plan.json')))
        write(root,'run-complete.json',dict(complete=True,measured_requests=48,calibration_requests=2,phases=phases,
             trace_sha256=digest(root/'trace.json'),plan_sha256=digest(root/'plan.json')))
        (root/'requests').mkdir()
        for key in keys:shutil.copy2(SOURCE/'requests'/f'{key}.json',root/'requests')
        for name in ['worker','service','scheduler']:
            original=SOURCE/(name+'.jsonl')
            handle=original.open() if original.exists() else gzip.open(str(original)+'.gz','rt')
            with handle,(root/(name+'.jsonl')).open('w') as output:
                for line in handle:
                    e=json.loads(line)
                    if e.get('key') in keys or (name=='scheduler' and e['event']=='step' and any(r['key'] in keys for r in e['active'])):
                        output.write(line)
        shutil.copytree(SOURCE/'sources',root/'sources')
        lock=json.loads((SOURCE/'source-lock.json').read_text());write(root,'source-lock.json',lock)
        write(root,'candidate-lock.json',dict(files=lock))
        inputs=json.loads((SOURCE/'problems100.json').read_text())
        sparse=[inputs[i] if i<12 else None for i in range(500)]
        write(root,'problems100.json',sparse)
        write(root,'dataset-manifest.json',dict(sparse_input_sha256=digest(root/'problems100.json'),first_100_equal_saved=True,rows=500,unique_ids=500))
        write(root,'exposure-audit.json',dict(selected_disjoint_from_observed_generation=True))
        write(root,'runtime-fit.json',dict(passed=True))
        inputs=['plan.json','candidate-lock.json','problems100.json','dataset-manifest.json','exposure-audit.json']
        versions=json.loads((SOURCE/'manifest.json').read_text())['versions']
        write(root,'manifest.json',dict(shard=0,condition='late_burst',sources=lock,versions=versions,input_hashes={n:digest(root/n) for n in inputs}))
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_real_baseline(self):
        result=validate(self.root)
        self.assertTrue(result['passed']);self.assertEqual(result['measured_requests'],48)
        self.assertEqual(result['binding_live_cutoffs'],2)
    def test_client_clock_corruption_rejected(self):
        p=self.root/'run-complete.json';original=p.read_bytes();d=json.loads(original)
        d['phases'][1]['client'][0]['client_finished']=d['phases'][1]['client'][0]['scheduled']-1
        try:
            write(self.root,p.name,d)
            with self.assertRaises(AssertionError):validate(self.root)
        finally:p.write_bytes(original)
    def test_cue_corruption_rejected(self):
        p=self.root/'requests/b0-live-01.json';original=p.read_bytes();d=json.loads(original);d['token_ids'][2048]=-999
        try:
            write(self.root,str(p.relative_to(self.root)),d)
            with self.assertRaises(AssertionError):validate(self.root)
        finally:p.write_bytes(original)
    def test_source_corruption_rejected(self):
        p=next((self.root/'sources').rglob('metrics.py'));original=p.read_bytes()
        try:
            p.write_bytes(original+b'\n# corruption\n')
            with self.assertRaises(AssertionError):validate(self.root)
        finally:p.write_bytes(original)

if __name__=='__main__':unittest.main()
