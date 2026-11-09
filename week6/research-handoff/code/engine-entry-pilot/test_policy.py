import unittest
from control import RequestControl,move_rows
from queue_policy import arrival_budget,apply_pressure,forced_token
class PressureTests(unittest.TestCase):
 def state(self,n=0):return RequestControl('p--r0',[1]*n,8192,[7,9,6],9,0,answer_cap=8)
 def test_below4k_stops_at4k(self):
  s=self.state(2000);self.assertTrue(apply_pressure(s,'live',1));self.assertIsNone(forced_token(s));s.output.extend([1]*2096);self.assertEqual(forced_token(s),7);self.assertEqual(s.force_start,4096)
 def test_above4k_cues_now_without_rewind(self):
  s=self.state(5000);before=s.output[:];self.assertTrue(apply_pressure(s,'live',1));self.assertEqual(forced_token(s),7);self.assertEqual(s.force_start,5000);self.assertEqual(s.output,before)
 def test_natural_close_and_answer_untouched(self):
  for suffix in [[9],[9,2,3]]:
   s=self.state(100);s.output.extend(suffix);self.assertFalse(apply_pressure(s,'live',8));self.assertIsNone(forced_token(s))
 def test_cue_and_cap_preserved(self):
  s=self.state(5000);apply_pressure(s,'live',1)
  for expected in s.cue:self.assertEqual(forced_token(s),expected);s.output.append(expected)
  self.assertFalse(apply_pressure(s,'live',1));self.assertEqual(s.answer_cap,8)
  while len(s.output)-s.close_index-1<8:s.output.append(2)
  self.assertEqual(forced_token(s),0)
 def test_recovery_new_admissions_not_reextend_cut(self):
  s=self.state();apply_pressure(s,'live',1);self.assertEqual(s.budget,4096);self.assertFalse(apply_pressure(s,'live',0));self.assertEqual(s.budget,4096)
  self.assertEqual(arrival_budget('live',0),8192);self.assertEqual(arrival_budget('live',1),4096)
 def test_fixed_and_arrival_never_live_cut(self):
  for mode in ['fixed4k','fixed8k','arrival']:self.assertFalse(apply_pressure(self.state(5000),mode,9))
  self.assertEqual(arrival_budget('fixed8k',9),8192);self.assertEqual(arrival_budget('fixed4k',0),4096)
 def test_state_survives_row_moves_and_removal(self):
  a,b=self.state(5000),self.state(200);b.key='p--r1';rows={0:a,1:b};move_rows(rows,[(0,1,True)]);self.assertIs(rows[1],a);apply_pressure(rows[1],'live',1);self.assertEqual(forced_token(a),7);del rows[1];self.assertIs(rows[0],b)
 def test_repeated_update_idempotent(self):
  s=self.state();self.assertTrue(apply_pressure(s,'live',1));v=s.version;self.assertFalse(apply_pressure(s,'live',2));self.assertEqual(s.version,v)
 def test_invalid_configuration(self):
  with self.assertRaises(ValueError):arrival_budget('typo',0)
  with self.assertRaises(ValueError):arrival_budget('live',-1)
if __name__=='__main__':unittest.main()
