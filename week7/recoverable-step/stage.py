"""Stage the existing shared-prefix engine with locked AIME 2026 inputs."""
import argparse
import hashlib
import json
import re
import shutil
import unicodedata
from pathlib import Path

import pyarrow.parquet as pq

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SOURCE = REPO / 'week6/shared-prefix-study'
REVISION = 'd61f486805306e6e6b5913504c07763a99e1b112'


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text):
    return re.sub(r'[\s$\\{}]', '', unicodedata.normalize('NFKC', text).casefold())


def strings(data):
    if isinstance(data, list):
        for item in data:
            yield from strings(item)
    elif isinstance(data, dict):
        for key, value in data.items():
            if key in {'question', 'problem', 'prompt', 'problem_text'} and isinstance(value, str):
                yield value
            elif isinstance(value, (dict, list)):
                yield from strings(value)


def replace(path, original, replacement):
    text = path.read_text()
    assert text.count(original) == 1, path
    path.write_text(text.replace(original, replacement))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', type=Path)
    parser.add_argument('gpu', choices=['L40S', 'A100', 'A40'])
    args = parser.parse_args()
    rows = sorted(pq.read_table(HERE / 'inputs/source.parquet').to_pylist(), key=lambda row: row['problem_idx'])
    prior = set()
    for path in REPO.glob('week[1-6]/**/*.json'):
        if path.name.startswith(('problem', 'question', 'dataset', 'input', 'request')) and path.stat().st_size < 3_000_000:
            prior.update(normalize(value) for value in strings(json.loads(path.read_text())))
    normalized = [normalize(row['problem']) for row in rows]
    assert len(rows) == len(set(normalized)) == 30
    assert all(0 <= row['answer'] <= 999 for row in rows)
    overlap = [row['problem_idx'] for row, text in zip(rows, normalized) if text in prior]
    assert not overlap, overlap

    stage = args.stage.resolve()
    target = stage / 'week6/shared-prefix-study'
    inputs = target / 'inputs'
    inputs.mkdir(parents=True)
    for name in ['run.py', 'protocol.py', 'control.py', 'worker.py', 'analyze.py', 'freeze.py',
                 'test_protocol.py', 'spec.json', 'model-files.json', 'regression-prefix.json']:
        shutil.copyfile(SOURCE / name, target / name)
    common = stage / 'week6/aime-budget-screen'
    common.mkdir()
    shutil.copyfile(REPO / 'week6/aime-budget-screen/common.py', common / 'common.py')
    for file in ['source.parquet', 'MathArena-README.md']:
        shutil.copyfile(HERE / 'inputs' / file, inputs / file)
    write(inputs / 'questions.json', [
        dict(id=index, stable_id=f"aime2026:{row['problem_idx']}", problem=row['problem'],
             answer=row['answer'], split='evaluation')
        for index, row in enumerate(rows, 1)
    ])
    write(inputs / 'manifest.json', dict(
        repository='MathArena/aime_2026', revision=REVISION, license='CC-BY-NC-SA-4.0',
        source_sha256=digest(inputs / 'source.parquet'), questions=30, normalized_prior_strings=len(prior),
        exact_overlap=overlap,
    ))
    spec = json.loads((target / 'spec.json').read_text())
    spec.update(name='larb-recoverable-step-v1', gpu_type=args.gpu.lower(),
                seed_bases=[761226, 771226], measurement_timeout_seconds=12600)
    write(target / 'spec.json', spec)
    replace(target / 'protocol.py', "sum(r['split'] == 'evaluation' for r in rows) == 40",
            "sum(r['split'] == 'evaluation' for r in rows) == 60")
    replace(target / 'run.py', "assert 'L40S' in device, f'Frozen L40S allocation required, got {device}'",
            "assert spec['gpu_type'].upper() in device.upper(), f'Unexpected allocated GPU {device}'")
    replace(target / 'run.py', "            # Seal calibration before generating any evaluation question.\n            if item == schedule()[19]:\n                from analyze import seal_calibration\n                seal_calibration(args.out)\n", '')
    replace(target / 'test_protocol.py', "self.assertEqual(sum(r['split']=='calibration' for r in rows),20)",
            "self.assertEqual(sum(r['split']=='evaluation' for r in rows),60)")
    shutil.copyfile(HERE / 'PLAN.md', target / 'PROTECTED-PLAN.md')
    shutil.copyfile(HERE / 'run.sbatch', stage / 'run.sbatch')
    print(f'Staged 30 protected questions. No exact overlap against {len(prior)} normalized prior strings.')


if __name__ == '__main__':
    main()
