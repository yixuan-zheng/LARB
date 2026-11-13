"""CPU checks against a synthetic token stream and the frozen real checkpoints."""
import tempfile
import unittest
from pathlib import Path

from control import RequestControl
from protocol import JoinedTokens, atomic, read, token_hash
from score import estimates, grade, summarize
from study import HERE, call_inputs, can_start, checkpoint, completed, engineering_gate, finish, next_attempt, pilot_metrics, schedule, verify_release

OPEN, CLOSE, EOS, SAFE = 10, 11, 12, 13
CUE = [14, CLOSE, 15]


def fixture():
    prefix = [OPEN]+[SAFE]*4095
    return dict(close_id=CLOSE, eos_id=EOS, cue_ids=CUE, previous_seeds=[],
                prefixes={'toy':dict(id=1, prompt_token_ids=[20], prefix_token_ids=prefix,
                                     prefix_hash=token_hash(prefix))})


def task(arm='short'):
    return next(t for t in schedule(fixture(), 'pilot') if t['arm']==arm)


class ContinuationTests(unittest.TestCase):
    def test_real_release_and_seeds(self):
        verify_release()
        data = read(HERE/'prefixes.json')
        self.assertEqual(len(data['prefixes']), 58)
        self.assertTrue(all(set(p)=={'id','prefix_hash','prefix_token_ids','prompt_token_ids'}
                            for p in data['prefixes'].values()))
        full, pilot = schedule(data, 'full'), schedule(data, 'pilot')
        self.assertEqual((len(full),len(pilot)), (928,12))
        self.assertEqual(len({data['prefixes'][t['prefix_key']]['id'] for t in pilot}), 3)
        self.assertEqual(full, schedule(data, 'full'))
        seeds = {t['seed'] for t in full}
        self.assertEqual(len(seeds), len(full))
        self.assertFalse(seeds & set(data['previous_seeds']))
        by_id = {t['call_id']: t for t in full}
        self.assertTrue(all(by_id[t['call_id']] == t for t in pilot))
        self.assertEqual(full[:12], pilot)
        for t in full:
            ids, prefix = call_inputs(data, t, 151667)
            self.assertEqual(ids[-4096:], prefix)

    def test_shared_checkpoint_and_independent_control(self):
        data = fixture()
        first, prefix = call_inputs(data, task(), OPEN)
        second, other = call_inputs(data, task('long'), OPEN)
        self.assertEqual(first, second)
        a, b = [], []
        short = RequestControl('short', JoinedTokens(prefix, a), 4096, CUE, CLOSE, EOS, 4)
        long = RequestControl('long', JoinedTokens(other, b), 8192, CUE, CLOSE, EOS, 4)
        self.assertIsNone(long.next_forced())
        for token in CUE:
            self.assertEqual(short.next_forced(), token)
            a.append(token)
        self.assertIsNone(short.next_forced())
        a.extend([SAFE]*3)
        self.assertEqual(short.next_forced(), EOS)
        a.append(EOS)
        self.assertEqual(finish(data, task(), prefix, a, 4, OPEN)['reason'], 'answer_cap')
        self.assertEqual(len(other), 4096)
        b.extend([SAFE]*4096)
        self.assertEqual(long.next_forced(), CUE[0])
        self.assertTrue(finish(data, task('long'), other, b+CUE+[SAFE,EOS], 4, OPEN)['normal'])
        early = finish(data, task('long'), other, [SAFE,CLOSE,SAFE,EOS], 4, OPEN)
        self.assertTrue(early['normal'])
        self.assertFalse(early['forced'])
        self.assertFalse(finish(data, task(), prefix, [CLOSE,SAFE,EOS], 4, OPEN)['normal'])
        data['prefixes']['toy']['prefix_token_ids'][50] = CLOSE
        with self.assertRaises(ValueError):
            call_inputs(data, task(), OPEN)

    def test_grading_and_uncertainty(self):
        self.assertEqual(grade(None, 4), (None,'missing'))
        self.assertEqual(grade(dict(normal=True,final_text=r'\boxed{004}'),4),(1,'graded'))
        self.assertEqual(grade(dict(normal=False,final_text=r'\boxed{4}',reason='answer_cap'),4),
                         (0,'answer_cap'))
        self.assertEqual(grade(dict(normal=True,final_text=r'\boxed{3}\boxed{4}'),4)[0],0)
        r = estimates(dict(short=[1,0],long=[1,1]))
        self.assertEqual((r['delta'],r['independent_draw_gain'],r['independent_draw_loss']),(.5,.5,0))
        r = estimates(dict(short=[1,None],long=[0,None]))
        self.assertIsNone(r['delta'])
        self.assertEqual(r['delta_missing_data_bounds'],[-1.,0.])

    def test_checkpoint_resume_and_conflicts(self):
        data = fixture()
        t = task()
        tokens, prefix = call_inputs(data, t, OPEN)
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            with checkpoint(root, {'release':'first'}):
                interrupted = next_attempt(root,t['call_id'],'job1')
                self.assertIsNone(completed(root,t,data))
                with self.assertRaises(BlockingIOError):
                    with checkpoint(root, {'release':'first'}):
                        self.fail('second writer admitted')
            with checkpoint(root, {'release':'first'}):
                self.assertEqual(read(interrupted)['status'],'started')
                resumed = next_attempt(root,t['call_id'],'job2')
                self.assertEqual(resumed.name,'002.json')
                suffix = CUE+[SAFE,EOS]
                record = dict(task=t,input_hash=token_hash(tokens),prefix_hash=token_hash(prefix),
                              suffix_token_ids=suffix,suffix_hash=token_hash(suffix),
                              normal=True,final_text=r'\boxed{4}')
                path = root/'calls'/f"{t['call_id']}.json"
                atomic(path,record)
                self.assertEqual(completed(root,t,data),record)
                summary = summarize(data,schedule(data,'pilot'),root,{1:4})
                self.assertEqual(summary['prefixes']['toy']['arms']['short']['successes'],1)
                self.assertIsNone(summary['cohort'])
                atomic(path,{**record,'suffix_token_ids':[EOS]})
                with self.assertRaises(ValueError):
                    completed(root,t,data)
            with self.assertRaises(ValueError):
                with checkpoint(root, {'release':'changed'}):
                    self.fail('changed release accepted')

    def test_pilot_metrics_require_normal_answers_in_both_arms(self):
        records = [
            dict(task=dict(arm=arm), normal=True, reason='normal', forced=arm=='short',
                 elapsed_seconds=10, first_output_seconds=.2, suffix_token_ids=[1,2],
                 memory_free_after_bytes=500)
            for arm in ('short','long') for _ in range(6)
        ]
        self.assertTrue(pilot_metrics(records)['mechanics_passed'])
        records[-1]['reason'] = 'invalid_token_protocol'
        self.assertFalse(pilot_metrics(records)['mechanics_passed'])

    def test_integrated_gate_and_allocation_reserve(self):
        data = read(HERE/'prefixes.json')
        tasks = schedule(data, 'pilot')
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'calls').mkdir()
            atomic(root/'session-test.json', {'start_seconds': 25})
            self.assertFalse(engineering_gate(root, tasks, data, 300, 600))
            for t in tasks:
                ids, prefix = call_inputs(data, t, 151667)
                suffix = data['cue_ids']+[data['eos_id']]
                record = dict(task=t, job='test', input_hash=token_hash(ids), prefix_hash=token_hash(prefix),
                              suffix_token_ids=suffix, suffix_hash=token_hash(suffix),
                              normal=True, reason='normal', forced=True, elapsed_seconds=12,
                              first_output_seconds=.2, memory_free_after_bytes=1000)
                atomic(root/'calls'/f"{t['call_id']}.json", record)
            self.assertTrue(engineering_gate(root, tasks, data, 300, 600))
            path = root/'calls'/f"{tasks[-1]['call_id']}.json"
            atomic(path, {**read(path), 'memory_free_after_bytes': 0})
            with self.assertRaises(RuntimeError):
                engineering_gate(root, tasks, data, 300, 600)
            self.assertFalse(read(root/'engineering-gate.json')['passed'])
        self.assertTrue(can_start(1000, 670, 300))
        self.assertFalse(can_start(1000, 671, 300))

    def test_nonempty_foreign_directory_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root/'forecasts.jsonl').touch()
            with self.assertRaises(ValueError):
                with checkpoint(root, {'release':'track-b'}):
                    self.fail('foreign output accepted')
            self.assertFalse((root/'manifest.json').exists())
            self.assertFalse((root/'run.lock').exists())


if __name__ == '__main__':
    unittest.main()
