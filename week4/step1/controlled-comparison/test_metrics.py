import unittest
from metrics import finish_kind, outcome, summarize


class MetricTests(unittest.TestCase):
    def raw(self):
        return dict(finished=True,finish_reason='stop',token_ids=[1,9,4,0],close_id=9,eos_id=0)

    def test_correct_cap_is_failure_even_when_vllm_reports_stop(self):
        for cap in ['thinking_cap','answer_cap']:
            finish=finish_kind(self.raw(),cap)
            self.assertEqual(outcome(True,finish,5,10),dict(completed_correct=False,correct_on_time=False))

    def test_late_correct_remains_eventually_correct(self):
        self.assertEqual(outcome(True,'normal',11,10),dict(completed_correct=True,correct_on_time=False))

    def test_boundary_deadline_and_wrong_answer(self):
        self.assertTrue(outcome(True,'normal',10,10)['correct_on_time'])
        self.assertFalse(outcome(False,'normal',1,10)['correct_on_time'])

    def test_missing_final_and_unfinished_reasoning_cannot_pass(self):
        self.assertEqual(finish_kind(None),'missing_final')
        raw=self.raw();raw['token_ids']=[1,4,0]
        self.assertEqual(finish_kind(raw),'missing_thinking_close')
        self.assertFalse(outcome(True,finish_kind(raw),1,10)['completed_correct'])

    def test_clock_inversion_rejected(self):
        with self.assertRaises(ValueError):
            outcome(True,'normal',-1,10)

    def test_fixed_horizon_includes_failed_and_late_requests(self):
        base=dict(live_reduction=False,binding_live_cutoff=False,thinking_tokens=1,answer_tokens=1)
        rows=[dict(base,finish='normal',client_completion_seconds=5,**outcome(True,'normal',5,10)),
              dict(base,finish='normal',client_completion_seconds=12,**outcome(True,'normal',12,10)),
              dict(base,finish='missing_final',client_completion_seconds=None,**outcome(False,'missing_final',None,10))]
        result=summarize(rows,20)
        self.assertEqual((result['n'],result['correct_on_time'],result['completed_correct']),(3,1,2))
        self.assertEqual(result['correct_on_time_per_minute'],3)
        self.assertEqual(result['terminal_receipts'],2)


if __name__=='__main__':
    unittest.main()
