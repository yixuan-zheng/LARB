"""Stage only exact saved IDs and metadata. Keep outcomes local."""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
RUNS = {
    'week6': REPO / 'week6/shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix',
    'week7': HERE.parent.parent / 'recoverable-step/results/job-6958397',
}


def read(path):
    return json.loads(path.read_text())


def token_hash(ids):
    return hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('stage', type=Path)
    parser.add_argument('upstream', type=Path)
    args = parser.parse_args()
    config = read(HERE/'config.json')
    rows = []
    for cohort, root in RUNS.items():
        manifest = read(root/'manifest.json')
        assert manifest['model_revision'] == config['revision']
        assert read(root/'status.json')['complete']
        for item in read(root/'schedule.json'):
            key = item['key']
            pair = read(root/'pairs'/f'{key}.json')
            if not pair['eligible']:
                continue
            raw = read(root/'calls'/f'{key}-prefix.json')
            prompt, prefix = pair['prompt_token_ids'], pair['prefix_token_ids']
            assert raw['input_token_ids'] == prompt and raw['token_ids'] == prefix
            assert len(prefix) == 4096 and token_hash(prefix) == pair['prefix_hash']
            assert not {manifest['close_id'], manifest['eos_id']} & set(prefix)
            rows.append(dict(key=f'{cohort}:{key}', question=f"{cohort}:{item['id']}",
                             prompt=prompt, prefix=prefix, input_hash=token_hash(prompt+prefix)))
    assert len(rows) == 115 and len({r['question'] for r in rows}) == 59
    root = args.stage
    root.mkdir()
    (root/'inputs.json').write_text(json.dumps(rows, separators=(',', ':'))+'\n')
    for name in ('config.json','prepare.py','extract.py','run.sbatch','PROTOCOL.md'):
        shutil.copyfile(HERE/name, root/name)
    model_files = RUNS['week7']/'sources/week6/shared-prefix-study/model-files.json'
    shutil.copyfile(model_files, root/'model-files.json')
    shutil.copyfile(args.upstream/'src/probing/features.py', root/'upstream_features.py')
    lock = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.iterdir())}
    (root/'release-lock.json').write_text(json.dumps(lock, indent=2)+'\n')


if __name__ == '__main__':
    main()
