import json
from pathlib import Path
import unittest
from execution import trace_for

PLAN=json.loads((Path(__file__).resolve().parents[1]/'evaluation-plan/plan.json').read_text())
def calibration(durations=(40.,60.)):
    return dict(client=[dict(status='terminal',scheduled=100.,client_finished=100+d) for d in durations])

class TraceContracts(unittest.TestCase):
    def test_three_traces_and_rotated_position_identity(self):
        expected={'low_load':[120*i for i in range(12)],'late_burst':[0,0]+[10+.05*i for i in range(10)],'sustained_pressure':[18*i for i in range(12)]}
        for shard in [0,1]:
            for condition,offsets in expected.items():
                t=trace_for(PLAN,shard,condition,calibration(),200.)
                self.assertEqual(t['relative_deadline_seconds'],120.)
                self.assertEqual(t['observation_horizon_seconds'],max(offsets)+120.)
                for b in [0,1]:
                    self.assertEqual([r['index'] for r in t['arrivals_by_block'][b]],PLAN['sample']['shards'][shard]['block_positions'][b])
                    self.assertEqual([r['offset_seconds'] for r in t['arrivals_by_block'][b]],offsets)
    def test_incomplete_or_invalid_calibration_rejected(self):
        for d in [dict(client=[]),dict(client=[dict(status='error')]*2),calibration((0.,60.))]:
            with self.assertRaises(ValueError):trace_for(PLAN,0,'late_burst',d,200.)
    def test_minimum_unit_is_30_not_minimum_deadline_30(self):
        self.assertEqual(trace_for(PLAN,0,'low_load',calibration((2.,3.)),200.)['relative_deadline_seconds'],60.)
    def test_unknown_condition_rejected(self):
        with self.assertRaises(ValueError):trace_for(PLAN,0,'invented',calibration(),200.)

if __name__=='__main__':unittest.main()
