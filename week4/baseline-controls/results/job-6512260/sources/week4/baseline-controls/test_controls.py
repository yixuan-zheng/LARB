import unittest
from w4_policy import attach_admission, arrival_decision, make_control, reduce_live, forced_token
from execution import trace_for
import json
from pathlib import Path

class Controls(unittest.TestCase):
    def data(self,policy):
        return dict(key='b0-'+policy+'-001',policy=policy,budget=16384,cue=[7,9,6],close_id=9,eos_id=0,answer_cap=3)
    def snapshot(self,policy,n):
        return dict(step=1,monotonic=1.,waiting=['b0-'+policy+'-'+str(i+10) for i in range(n)],active=[])
    def test_static_pressure_independent_and_never_revised(self):
        for policy,budget in [('fixed2048',2048),('fixed4096',4096)]:
            for n in [0,1,2,10]:
                data=self.data(policy);snap=self.snapshot(policy,n)
                self.assertEqual(arrival_decision(policy,snap,'b0-'+policy,1.1,2)['budget'],budget)
                attach_admission(data,snap);self.assertEqual(data['budget'],budget)
                state=make_control(data,[]);state.output.append(1)
                self.assertFalse(reduce_live(state,policy,10));self.assertEqual(state.budget,budget)
    def test_fixed_boundaries_full_cue_answer_cap(self):
        for policy,budget in [('fixed2048',2048),('fixed4096',4096)]:
            data=self.data(policy);attach_admission(data,self.snapshot(policy,0));state=make_control(data,[])
            state.output.extend([1]*(budget-1));self.assertIsNone(forced_token(state)[0])
            state.output.append(1)
            for token in data['cue']:
                self.assertEqual(forced_token(state)[0],token);state.output.append(token)
            self.assertIsNone(forced_token(state)[0]);state.output.extend([2,2])
            self.assertEqual(forced_token(state),(0,'answer_cap'))
    def test_natural_closure_bypasses_cut(self):
        for policy in ['fixed2048','fixed4096']:
            data=self.data(policy);attach_admission(data,self.snapshot(policy,0));s=make_control(data,[1,9])
            self.assertIsNone(forced_token(s)[0]);self.assertIsNone(s.force_start)
    def test_original_admission_live_rule_preserved(self):
        for n in [0,1,2,5]:
            for policy in ['admission','live']:
                d=self.data(policy);attach_admission(d,self.snapshot(policy,n));self.assertEqual(d['budget'],2048 if n>=2 else 16384)
    def test_plan_trace_coverage_and_rotation(self):
        p=json.loads(Path(__file__).with_name('plan.json').read_text())
        calibration=dict(client=[dict(status='terminal',scheduled=0,client_finished=40),dict(status='terminal',scheduled=0,client_finished=60)])
        for shard,condition,n in [(0,'late_burst',12),(0,'sustained_pressure',12),(1,'gate',3)]:
            t=trace_for(p,shard,condition,calibration,100)
            self.assertEqual(len(t['arrivals_by_block'][0]),n)
            self.assertEqual(set(r['index'] for r in t['arrivals_by_block'][0]),set(r['index'] for r in t['arrivals_by_block'][1]))
        self.assertEqual(p['orders'][0],list(reversed(p['orders'][1])))

if __name__=='__main__':unittest.main()
