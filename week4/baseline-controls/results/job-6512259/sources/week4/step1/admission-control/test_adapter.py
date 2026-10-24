"""Exercise the real Week 4 bridge with small native-shaped engine fixtures."""
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from test_policy import data, snapshot
from w4_policy import LONG, SHORT


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.events = []
        self.snap = snapshot(count=2)
        owner = self

        class Audit:
            def schedule(self):
                self.audit_step = 5
                return self.result

        class Processor:
            def __init__(self, *args):
                self.rows, self.policies, self.caps = {}, {}, set()

        legacy = ModuleType('adapter')
        legacy.QueueAuditScheduler, legacy.BurstProcessor = Audit, Processor
        legacy.read_pressure = lambda: owner.snap
        legacy.emit = lambda stream,event,**kw: owner.events.append(dict(stream=stream,event=event,**kw))
        interface = ModuleType('vllm.v1.sample.logits_processor.interface')
        interface.MoveDirectionality = SimpleNamespace(SWAP=object())
        with patch.dict(sys.modules, {'adapter':legacy,
                        'vllm.v1.sample.logits_processor.interface':interface}):
            spec = importlib.util.spec_from_file_location('_w4_bridge_test',
                                                          Path(__file__).with_name('w4_adapter.py'))
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)

    def test_scheduler_attaches_before_return_and_preserves_stock_schedule(self):
        scheduler = self.module.AdmissionScheduler()
        params = [SimpleNamespace(extra_args={'burst':data(key=f'live-{i:02d}')}) for i in range(2)]
        scheduler.result = SimpleNamespace(scheduled_new_reqs=[SimpleNamespace(sampling_params=p)
                                           for p in params], num_scheduled_tokens={'a':15,'b':17})
        result = scheduler.schedule()
        self.assertIs(result, scheduler.result)
        self.assertEqual(result.num_scheduled_tokens, {'a':15,'b':17})
        self.assertTrue(all(p.extra_args['burst']['budget']==SHORT for p in params))
        self.assertEqual(len(self.events),2)
        self.assertEqual(params[0].extra_args['burst']['admission'],params[1].extra_args['burst']['admission'])

    def test_scheduler_rejects_wrong_step_snapshot(self):
        scheduler = self.module.AdmissionScheduler()
        scheduler.result = SimpleNamespace(scheduled_new_reqs=[])
        self.snap['step'] = 6
        with self.assertRaises(RuntimeError):
            scheduler.schedule()

    def test_worker_uses_transport_even_if_latest_queue_differs(self):
        scheduler = self.module.AdmissionScheduler()
        d = data()
        params = SimpleNamespace(extra_args={'burst':d})
        scheduler.result = SimpleNamespace(scheduled_new_reqs=[SimpleNamespace(sampling_params=params)])
        scheduler.schedule()
        self.snap = snapshot(count=0,step=100)
        processor = self.module.AdmissionProcessor(None,None,None)
        processor.update_state(SimpleNamespace(removed=[],added=[(0,params,[],[])],moved=[]))
        self.assertEqual(processor.rows[0].budget,SHORT)
        admitted = next(e for e in self.events if e['event']=='admitted')
        self.assertEqual(admitted['admission_step'],5)
        self.assertEqual(len(admitted['waiting']),2)

    def test_admission_cannot_change_and_live_requires_progress(self):
        from w4_policy import attach_admission
        for mode in ['admission','live']:
            self.events.clear()
            d = data(mode)
            attach_admission(d,snapshot(mode,count=0))
            output = []
            params = SimpleNamespace(extra_args={'burst':d})
            self.snap = snapshot(mode,count=2,step=6)
            processor = self.module.AdmissionProcessor(None,None,None)
            processor.update_state(SimpleNamespace(removed=[],added=[(0,params,[],output)],moved=[]))
            self.assertEqual(processor.rows[0].budget,LONG)
            output.extend([1]*3000)
            processor.update_state(None)
            self.assertEqual(processor.rows[0].budget, SHORT if mode=='live' else LONG)
            changes = [e for e in self.events if e['event']=='live_reduction']
            self.assertEqual(len(changes),int(mode=='live'))

    def test_removed_and_readded_request_keeps_live_revision(self):
        from w4_policy import attach_admission
        d = data()
        attach_admission(d,snapshot(count=0))
        params = SimpleNamespace(extra_args={'burst':d})
        output = []
        p = self.module.AdmissionProcessor(None,None,None)
        p.update_state(SimpleNamespace(removed=[],added=[(0,params,[],output)],moved=[]))
        output.extend([1]*3000)
        p.update_state(None)
        p.update_state(SimpleNamespace(removed=[0],added=[(1,params,[],output)],moved=[]))
        self.assertEqual(p.rows[1].budget,SHORT)
        self.assertEqual(sum(e['event']=='admitted' for e in self.events),1)
        self.assertEqual(sum(e['event']=='resumed' for e in self.events),1)


if __name__=='__main__':
    unittest.main()
