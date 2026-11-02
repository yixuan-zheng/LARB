import json,unittest
from pathlib import Path
from workload import freeze_trace
class TraceTests(unittest.TestCase):
 def setUp(self):self.spec=json.loads((Path(__file__).parent/'spec.json').read_text());self.cal=[dict(policy=p,latency_seconds=t) for p in ['fixed4k','fixed8k'] for t in [90,100,110,120]]
 def test_coverage_pairing_and_recovery(self):
  trace=freeze_trace(self.spec,self.cal);self.assertEqual(trace['planned_measured_requests'],72)
  self.assertEqual(sum(len(c['arrivals'])*len(c['policy_order']) for c in trace['conditions']),72)
  for c in trace['conditions']:
   self.assertEqual(len({x['id'] for x in c['arrivals']}),len(c['arrivals']))
   self.assertGreater(c['horizon_seconds'],max(x['offset_seconds'] for x in c['arrivals']))
  burst=trace['conditions'][2]['arrivals'];self.assertGreater(burst[8]['offset_seconds']-burst[7]['offset_seconds'],300)
 def test_no_correctness_dependence(self):
  before=freeze_trace(self.spec,self.cal)
  for c in self.cal:c['correct']=False;c['reference']='secret'
  self.assertEqual(before,freeze_trace(self.spec,self.cal))
 def test_calibration_incomplete_rejected(self):
  with self.assertRaises(ValueError):freeze_trace(self.spec,self.cal[:-1])
if __name__=='__main__':unittest.main()
