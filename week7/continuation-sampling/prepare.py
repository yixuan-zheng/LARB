"""Build a self-contained, answer-key-free Track B release."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / 'recoverable-step/results/job-6958397'
SHARED = 'week6/shared-prefix-study'


def read(path):
    return json.loads(path.read_text())


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert read(SOURCE/'gate.json')['passed'] and read(SOURCE/'status.json')['complete']
    upstream = read(SOURCE/'source-lock.json')
    args.output.mkdir(parents=True, exist_ok=False)
    files = {}
    for name in ('control.py', 'protocol.py', 'worker.py', 'model-files.json'):
        path = f'{SHARED}/{name}'
        payload = (SOURCE/'sources'/path).read_bytes()
        assert digest(payload) == upstream[path], path
        files[name] = payload
    grader = 'week6/aime-budget-screen/common.py'
    files['common.py'] = (SOURCE/'sources'/grader).read_bytes()
    assert digest(files['common.py']) == upstream[grader]
    spec = read(SOURCE/'spec.json')
    assert digest((SOURCE/'spec.json').read_bytes()) == upstream[f'{SHARED}/spec.json']
    manifest = read(SOURCE/'manifest.json')
    assert manifest['source']['source_lock_sha256'] == digest((SOURCE/'source-lock.json').read_bytes())
    schedule = read(SOURCE/'schedule.json')
    previous_seeds = []
    for source in sorted((SOURCE/'calls').glob('*.json')):
        previous_seeds.append(read(source)['seed'])
    pairs = {}
    for item in schedule:
        pair = read(SOURCE/'pairs'/f"{item['key']}.json")
        assert pair['complete']
        if pair['eligible']:
            key = item['key']
            original = read(SOURCE/'calls'/f'{key}-prefix.json')
            assert original['input_token_ids'] == pair['prompt_token_ids']
            assert original['token_ids'] == pair['prefix_token_ids']
            pairs[key] = {field: pair[field] for field in
                          ('id', 'prefix_hash', 'prefix_token_ids', 'prompt_token_ids')}
    assert len(pairs) == 58
    questions_hash = digest((SOURCE/'questions.json').read_bytes())
    assert questions_hash == upstream[f'{SHARED}/inputs/questions.json']
    data = dict(questions_sha256=questions_hash, source_job=manifest['job'], upstream_lock_sha256=manifest['source']['source_lock_sha256'],
                dataset=manifest['dataset'], model_revision=manifest['model_revision'],
                close_id=manifest['close_id'], eos_id=manifest['eos_id'], cue_ids=manifest['cue_ids'],
                previous_seeds=sorted(set(previous_seeds)), prefixes=pairs)
    files['prefixes.json'] = (json.dumps(data, separators=(',', ':'))+'\n').encode()
    files['spec.json'] = (json.dumps(spec, indent=2)+'\n').encode()
    for name in ('study.py', 'run.py', 'score.py', 'test_study.py', 'full.sbatch', 'SPEC.md'):
        files[name] = (HERE/name).read_bytes()
    for name, payload in files.items():
        (args.output/name).write_bytes(payload)
    (args.output/'release-lock.json').write_text(
        json.dumps({name: digest(payload) for name, payload in files.items()}, indent=2)+'\n')


if __name__ == '__main__':
    main()
