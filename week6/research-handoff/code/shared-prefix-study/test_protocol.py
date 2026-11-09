import itertools
import tempfile
import unittest
from pathlib import Path

from control import RequestControl, move_rows
from protocol import JoinedTokens, audit, branch_seed, schedule, signal, synthetic_token, validate_thinking_opening, read, HERE, token_hash
from analyze import frontier, choose, metrics


class ProtocolTests(unittest.TestCase):
    def test_checkpoint_global_cue_and_cap(self):
        prefix=[7]*4096
        output=[]
        combined=JoinedTokens(prefix,output)
        state=RequestControl('x',combined,4096,[8,9,10],9,11,answer_cap=4)
        for token in [8,9,10]:
            self.assertEqual(state.next_forced(),token)
            output.append(token)
        self.assertIsNone(state.next_forced())
        output.extend([4,5,6])
        self.assertEqual(state.next_forced(),11)
        output.append(11)
        checked=audit(prefix+output,9,11,[8,9,10],4096,4)
        self.assertEqual(checked['reason'],'answer_cap')

    def test_long_remaining_counter(self):
        prefix=[7]*4096
        output=[7]*4095
        state=RequestControl('x',JoinedTokens(prefix,output),8192,[8,9],9,11)
        self.assertIsNone(state.next_forced())
        output.append(7)
        self.assertEqual(state.next_forced(),8)
        self.assertEqual(state.force_start,8192)

    def test_natural_close_before_checkpoint(self):
        prefix=[7]*20+[9]+[4,5]
        output=[]
        state=RequestControl('x',JoinedTokens(prefix,output),8192,[8,9],9,11,answer_cap=4)
        self.assertIsNone(state.next_forced())
        output.extend([4,5])
        self.assertEqual(state.next_forced(),11)

    def test_actual_failed_prefix_accepts_initial_opener_without_changes(self):
        fixture=read(HERE/'regression-prefix.json')
        ids=fixture['token_ids']
        self.assertEqual(len(ids),4096)
        self.assertEqual(ids[0],151667)
        self.assertNotIn(151668,ids)
        validate_thinking_opening(ids,151667,151668)
        self.assertEqual(token_hash(ids),fixture['token_hash'])
        self.assertLessEqual(signal(fixture['last256_sampled_logprobs'],256),0)
        output=[]
        state=RequestControl('regression',JoinedTokens(ids,output),4096,[8,151668,10],151668,11)
        self.assertEqual(state.next_forced(),8)
        self.assertEqual(state.force_start,4096)

    def test_reopening_after_close_is_rejected(self):
        for ids in [[7,9,8],[8,7,9,8]]:
            with self.assertRaisesRegex(AssertionError,'reopened'):
                validate_thinking_opening(ids,8,9)

    def test_extra_opening_before_close_is_rejected(self):
        for ids in [[7,8],[8,7,8]]:
            with self.assertRaisesRegex(AssertionError,'unexpected'):
                validate_thinking_opening(ids,8,9)

    def test_opening_absent_or_initial_is_valid(self):
        for ids in [[7,7],[8,7],[7,9,4],[8,7,9,4]]:
            validate_thinking_opening(ids,8,9)

    def test_controlled_early_answer_crosses_checkpoint(self):
        transcript=[7]*4090+[9]+[20,21,22,23,24,25,26,27,28,29]+[11]
        prefix=transcript[:4096]
        output=[]
        state=RequestControl('fixture',JoinedTokens(prefix,output),8192,[8,9,10],9,11)
        fixture=dict(sequence=transcript)
        while not output or output[-1]!=11:
            state.next_forced()
            token=synthetic_token(fixture,len(state.output))
            self.assertIsNotNone(token)
            output.append(token)
        self.assertEqual(prefix+output,transcript)
        checked=audit(prefix+output,9,11,[8,9,10],8192,2048)
        self.assertTrue(checked['normal'])
        self.assertFalse(checked['forced'])
        self.assertEqual(checked['close_index'],4090)

    def test_failed_run_multiple_close_remains_rejected(self):
        ids=[9]+[7]*560+[9]+[4]*208+[11]
        checked=audit(ids,9,11,[8,9,10],8192,2048)
        self.assertFalse(checked['normal'])
        self.assertEqual(checked['reason'],'missing_or_multiple_close')

    def test_fixture_stops_controlling_at_sequence_end(self):
        self.assertIsNone(synthetic_token(None,12))
        self.assertEqual(synthetic_token(dict(sequence=[4,9,11]),1),9)
        self.assertIsNone(synthetic_token(dict(sequence=[4,9,11]),3))
        self.assertEqual(synthetic_token(dict(until=4096,token=7),4095),7)
        self.assertIsNone(synthetic_token(dict(until=4096,token=7),4096))

    def test_legacy_cap_boundary(self):
        for answer_tokens,normal in [(3,True),(4,False)]:
            ids=[7,9]+[5]*answer_tokens+[11]
            self.assertEqual(audit(ids,9,11,[8,9],4096,4)['normal'],normal)

    def test_token_prefix_identity(self):
        prefix=[1,2,3];output=[4]
        joined=JoinedTokens(prefix,output)
        self.assertEqual(joined[:],[1,2,3,4])
        output.append(5)
        self.assertEqual(joined[-1],5)
        self.assertEqual(joined[3:],output)

    def test_schedule_and_seed(self):
        rows=schedule()
        self.assertEqual(len(rows),60)
        self.assertEqual(sum(r['split']=='calibration' for r in rows),20)
        self.assertEqual(len({r['key'] for r in rows}),60)
        self.assertNotEqual(branch_seed(22,'short'),branch_seed(22,'long'))

    def test_signal_excludes_extra_history(self):
        self.assertEqual(signal([-100.]*200+[-2.]*256,256),-2.)

    def test_frontier_handles_long_cheaper_and_accuracy_losses(self):
        rows=[dict(outcomes=dict(short=dict(correct=True,tokens=8),long=dict(correct=False,tokens=4))),
              dict(outcomes=dict(short=dict(correct=False,tokens=9),long=dict(correct=True,tokens=5)))]
        actual={r['correct']:r['tokens'] for r in frontier(rows)}
        expected={}
        for branches in itertools.product(['short','long'],repeat=2):
            correct=sum(rows[i]['outcomes'][b]['correct'] for i,b in enumerate(branches))
            cost=sum(rows[i]['outcomes'][b]['tokens'] for i,b in enumerate(branches))
            expected[correct]=min(cost,expected.get(correct,cost))
        self.assertEqual(actual,expected)

    def test_selector_uses_strict_checkpoint_threshold(self):
        row=dict(eligible=True,score=-2.,outcomes=dict(
            short=dict(correct=False,tokens=6000),long=dict(correct=True,tokens=9500)))
        self.assertEqual(choose(row,dict(kind='threshold',threshold=-2.)), 'short')
        self.assertEqual(choose(row,dict(kind='threshold',threshold=-1.9)), 'long')
        row['eligible']=False
        self.assertEqual(choose(row,dict(kind='long')), 'short')

    def test_cost_counts_shared_prefix_once_per_policy(self):
        row=dict(eligible=True,score=-2.,outcomes=dict(
            short=dict(correct=True,tokens=6000),long=dict(correct=True,tokens=9000)))
        self.assertEqual(metrics([row],dict(kind='short'))['tokens'],6000)
        self.assertEqual(metrics([row],dict(kind='long'))['tokens'],9000)

    def test_row_moves_preserve_history(self):
        output=[4]
        state=RequestControl('x',JoinedTokens([7]*4096,output),8192,[8,9],9,11)
        rows={1:state};move_rows(rows,[(1,0,False)])
        self.assertIs(rows[0],state)
        output.append(5)
        self.assertEqual(len(rows[0].output),4098)


if __name__=='__main__':
    unittest.main()
