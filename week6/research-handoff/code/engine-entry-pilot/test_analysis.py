import unittest
from analyze import completion
class CompletionTests(unittest.TestCase):
 def raw(self,ids):return dict(token_ids=ids,close_id=9,eos_id=0,cue_ids=[7,9,6],complete=True)
 def test_actual_late_cue_position(self):
  ids=[1]*5000+[7,9,6,2,0];self.assertTrue(completion(self.raw(ids),5000)['normal'])
  with self.assertRaises(ValueError):completion(self.raw(ids),4096)
 def test_cap_and_partial_retained(self):
  self.assertFalse(completion(self.raw([1,9]+[2]*2048+[0]))['normal'])
  self.assertFalse(completion(self.raw([1,9,2]))['normal'])
if __name__=='__main__':unittest.main()

class MissingCoverageTests(unittest.TestCase):
 def test_unstarted_phases_remain_in_denominator(self):
  import contextlib,io,json,tempfile
  from pathlib import Path
  from analyze import analyze
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'requests').mkdir();(root/'progress.json').write_text('[]');(root/'trace.json').write_text(json.dumps(dict(conditions=[dict(name='burst',policy_order=['fixed4k','fixed8k','live'],horizon_seconds=100,arrivals=[dict(slot=0,id=1,seed=6223,offset_seconds=0,relative_deadline_seconds=100)])])))
   with contextlib.redirect_stdout(io.StringIO()):result=analyze(root)
   self.assertEqual(result['planned'],3);self.assertEqual(len(result['rows']),3)
   self.assertTrue(all(not x['present'] and not x['good'] for x in result['rows']))

class ProbeAccountingTests(unittest.TestCase):
 def test_43_counts_and_probe_separation_even_before_start(self):
  import json,tempfile,contextlib,io
  from pathlib import Path
  from analyze import analyze
  from gate import probe_plan
  from workload import ranked_ids
  here=Path(__file__).parent;spec=json.loads((here/'spec.json').read_text());trace=json.loads((here/'trace-r0.json').read_text())
  with tempfile.TemporaryDirectory() as folder:
   root=Path(folder);(root/'requests').mkdir();(root/'progress.json').write_text('[]');(root/'trace.json').write_text(json.dumps(trace));(root/'probe-plan.json').write_text(json.dumps(probe_plan(spec,ranked_ids(spec['selection_salt'])[:4])))
   with contextlib.redirect_stdout(io.StringIO()):r=analyze(root)
   self.assertEqual(r['planned'],43);self.assertEqual(r['planned_measured'],36);self.assertEqual(r['planned_probes'],7)
