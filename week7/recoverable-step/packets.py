"""Build reader inputs without passing answer keys or suffixes to inference."""
import argparse
import hashlib
import json
import random
from pathlib import Path

from transformers import AutoTokenizer


def read(path):
    return json.loads(path.read_text())


def write(path, value):
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('run', type=Path)
    parser.add_argument('tokenizer', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    assert read(args.run / 'status.json')['complete']
    assert read(args.run / 'gate.json')['passed']
    tokenizer = AutoTokenizer.from_pretrained(args.tokenizer, local_files_only=True)
    questions = {row['id']: row['problem'] for row in read(args.run / 'questions.json')}
    entries = []
    eligible_questions = set()
    schedule = read(args.run / 'schedule.json')
    assert len(schedule) == 60
    for item in schedule:
        pair = read(args.run / 'pairs' / f"{item['key']}.json")
        assert pair['complete']
        if pair['eligible']:
            ids = pair['prefix_token_ids']
            assert len(ids) == 4096
            encoded = json.dumps(ids, separators=(',', ':')).encode()
            assert hashlib.sha256(encoded).hexdigest() == pair['prefix_hash']
            eligible_questions.add(item['id'])
            excerpt = tokenizer.decode(ids[-512:], clean_up_tokenization_spaces=False)
            entries.append(('bounded', item['key'], questions[item['id']], excerpt))
    entries.extend(('question', str(q), questions[q], '') for q in sorted(eligible_questions))
    random.Random(761226).shuffle(entries)
    args.output.mkdir(exist_ok=False, parents=True)
    mapping = {}
    direct = []
    step = []
    for index, (condition, key, question, prefix) in enumerate(entries, 1):
        case_id = f'case-{index:03d}'
        packet = dict(case_id=case_id, question=question, prefix=prefix)
        mapping[case_id] = dict(condition=condition, key=key)
        direct.append(packet)
        if condition == 'bounded':
            step.append(packet)
    for name, value in [('direct-packets', direct), ('step-packets', step), ('mapping', mapping)]:
        write(args.output / f'{name}.json', value)


if __name__ == '__main__':
    main()
