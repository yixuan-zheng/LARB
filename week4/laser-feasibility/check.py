"""Reproduce CPU contract tests and a deliberately scoped scalar microbenchmark."""
import hashlib
import json
import math
from pathlib import Path
import platform
import time
import unittest
from reference import Costs, Load, Parameters, budget, confidence

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

if __name__ == '__main__':
    suite = unittest.defaultTestLoader.discover(str(HERE), pattern='test_*.py')
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
    load = Load(Parameters(target=1)); times = []
    for i in range(5000):
        start = time.perf_counter_ns()
        budget(150, i % 3, load.params)
        load.observe_atp(i % 3)
        confidence([[(1, math.log(.98))]] * 20, complete=True, nonempty_answer=True)
        times.append(time.perf_counter_ns() - start)
    times.sort();costs = Costs()
    for i, kind in enumerate(['reason', 'probe', 'reason', 'final']):
        costs.record(str(i), kind=kind, prompt_tokens=1000, computed_prefill_tokens=1000,
            cached_tokens=0, decoded_tokens=20, discarded_tokens=20 if kind == 'probe' else 0,
            start=float(i), end=float(i + 1))
    lock = json.loads((REPO / 'week4/evaluation-plan/candidate-lock.json').read_text())['files']
    sources = {}
    for path in (REPO / 'week4/step1/admission-control').glob('w4_*.py'):
        name = str(path.relative_to(REPO)); digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == lock[name]
        sources[name] = digest
    report = dict(tests_run=result.testsRun, failures=0, python=platform.python_version(),
        gpu_allocations=0, model_generation_calls=0, dataset_questions_read=0,
        controller_files_unchanged=sources,
        microbenchmark=dict(iterations=5000,
            operation='budget + one global EMA/threshold update + 20-position confidence; synthetic scalar data only',
            median_microseconds=times[len(times) // 2] / 1000,
            p95_microseconds=times[math.ceil(.95 * len(times)) - 1] / 1000,
            limitation='Local CPU microbenchmark only; excludes tokenizer, IPC, serialization, GPU synchronization, probing, replay, and serving overhead.'),
        synthetic_accounting_example=dict(description='Four fabricated sequential calls, including one discarded probe; no inference was performed', totals=costs.totals()))
    (HERE / 'validation.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: 6B CPU contracts and unchanged controller hashes; no model inference.')
