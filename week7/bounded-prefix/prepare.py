"""Build outcome-blind packets using exact generator token slices."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from transformers import AutoTokenizer

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parents[1] / 'week6/shared-prefix-results/collection-6878140.IvHmeG/job-6878140-shared-prefix'


def write(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('tokenizer', type=Path)
    args = parser.parse_args()
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    questions = {row['id']: row['problem'] for row in json.loads((SOURCE / 'questions.json').read_text())}
    rows = [('question', str(key), text, '') for key, text in questions.items()]
    for path in sorted((SOURCE / 'pairs').glob('q*-b*.json')):
        pair = json.loads(path.read_text())
        if pair['eligible']:
            tokens = pair['prefix_token_ids']
            assert len(tokens) == 4096
            text = tokenizer.decode(tokens[-512:], clean_up_tokenization_spaces=False)
            rows.append(('bounded', pair['key'], questions[pair['id']], text))
    assert len(rows) == 87
    random.Random(751222).shuffle(rows)
    packets = []
    mapping = {}
    for index, (condition, key, question, prefix) in enumerate(rows):
        case_id = f'case-{index + 1:03d}'
        packets.append(dict(case_id=case_id, question=question, prefix=prefix))
        mapping[case_id] = dict(condition=condition, key=key)
    write(HERE / 'packets.json', packets)
    write(HERE / 'mapping.json', mapping)
    freeze = {
        name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
        for name in ['PLAN.md', 'prepare.py', 'read.py', 'score.py', 'reader-lock.json', 'packets.json', 'mapping.json']
    }
    write(HERE / 'freeze.json', freeze)


if __name__ == '__main__':
    main()
