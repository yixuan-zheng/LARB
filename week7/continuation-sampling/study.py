"""Pure-Python planning, token validation, and restartable result storage."""
import fcntl
import hashlib
import math
import statistics
from contextlib import contextmanager
from pathlib import Path

from protocol import atomic, audit, read, sha, token_hash, validate_thinking_opening

HERE = Path(__file__).resolve().parent
ARMS = {'short': 4096, 'long': 8192}


def verify_release(root=HERE):
    lock = root/'release-lock.json'
    for name, expected in read(lock).items():
        if sha(root/name) != expected:
            raise ValueError(f'Release hash mismatch: {name}')
    return sha(lock)


def rank(text):
    return hashlib.sha256(f'larb-track-b-v1:{text}'.encode()).digest()


def schedule(data, mode):
    keys = sorted(data['prefixes'], key=rank)
    selected = {}
    for key in keys:
        selected.setdefault(data['prefixes'][key]['id'], key)
    gate_keys = set(list(selected.values())[:3])
    if mode not in {'pilot', 'full'}:
        raise ValueError(mode)
    used = set(data['previous_seeds'])
    planned = []
    # Assign all seeds before filtering, so overlapping pilot/full calls keep the same seed.
    for key in sorted(data['prefixes']):
        for index in range(8):
            for arm, budget in ARMS.items():
                call_id = f'{key}-{arm}-{index:02d}'
                salt = 0
                while True:
                    seed = int.from_bytes(rank(f'seed:{call_id}:{salt}')[:4], 'big')
                    if seed not in used:
                        break
                    salt += 1
                used.add(seed)
                if mode == 'full' or (key in gate_keys and index < 2):
                    planned.append(dict(call_id=call_id, prefix_key=key, arm=arm, budget=budget,
                                        replicate=index, seed=seed))
    return sorted(planned, key=lambda row: (
        row['prefix_key'] not in gate_keys or row['replicate'] >= 2,
        row['replicate'], rank(row['call_id'])))


def call_inputs(data, task, opening):
    pair = data['prefixes'][task['prefix_key']]
    prefix = list(pair['prefix_token_ids'])
    prompt = list(pair['prompt_token_ids'])
    if len(prefix) != 4096 or token_hash(prefix) != pair['prefix_hash']:
        raise ValueError('Invalid saved checkpoint')
    if data['close_id'] in prefix or data['eos_id'] in prefix:
        raise ValueError('Checkpoint already closed')
    validate_thinking_opening(prefix, opening, data['close_id'])
    return prompt+prefix, prefix


def finish(data, task, prefix, suffix, answer_cap, opening):
    tokens = prefix+suffix
    try:
        validate_thinking_opening(tokens, opening, data['close_id'])
        return audit(tokens, data['close_id'], data['eos_id'], data['cue_ids'], task['budget'], answer_cap)
    except AssertionError as error:
        return dict(normal=False, reason='invalid_token_protocol', detail=str(error))


@contextmanager
def checkpoint(root, manifest):
    root.mkdir(parents=True, exist_ok=True)
    location = root/'manifest.json'
    if not location.exists() and any(path.name != 'run.lock' for path in root.iterdir()):
        raise ValueError('Refusing to initialize a nonempty run directory')
    with (root/'run.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if location.exists():
            if read(location) != manifest:
                raise ValueError('Resume manifest does not match')
        else:
            if any(path.name != 'run.lock' for path in root.iterdir()):
                raise ValueError('Refusing to initialize a nonempty run directory')
            atomic(location, manifest)
        (root/'calls').mkdir(exist_ok=True)
        (root/'attempts').mkdir(exist_ok=True)
        yield


def next_attempt(root, call_id, job):
    folder = root/'attempts'/call_id
    folder.mkdir(exist_ok=True)
    number = len(list(folder.glob('*.json'))) + 1
    path = folder/f'{number:03d}.json'
    atomic(path, dict(call_id=call_id, job=job, status='started'))
    return path


def completed(root, task, data):
    path = root/'calls'/f"{task['call_id']}.json"
    if not path.exists():
        return None
    record = read(path)
    pair = data['prefixes'][task['prefix_key']]
    expected = token_hash(pair['prompt_token_ids'] + pair['prefix_token_ids'])
    if (record['task'] != task or record['input_hash'] != expected or
            record['prefix_hash'] != pair['prefix_hash'] or
            record['suffix_hash'] != token_hash(record['suffix_token_ids'])):
        raise ValueError(f'Checkpoint record mismatch: {path.name}')
    return record


def pilot_metrics(records):
    arms = {}
    for arm in ARMS:
        group = [record for record in records if record['task']['arm'] == arm]
        if len(group) != 6:
            raise ValueError('Expected six records in each pilot arm')
        first = [r['first_output_seconds'] for r in group if r['first_output_seconds'] is not None]
        arms[arm] = dict(
            calls=len(group), normal=sum(r['normal'] for r in group),
            forced=sum(r.get('forced', False) for r in group),
            mean_seconds=statistics.mean(r['elapsed_seconds'] for r in group),
            mean_first_output_seconds=statistics.mean(first) if first else None,
            mean_suffix_tokens=statistics.mean(len(r['suffix_token_ids']) for r in group),
            min_sampled_free_bytes=min(r['memory_free_after_bytes'] for r in group),
        )
    valid = all(record['reason'] in {'normal', 'answer_cap'} for record in records)
    return dict(mechanics_passed=valid and all(a['normal'] > 0 for a in arms.values()),
                arms=arms, estimated_full_suffix_hours=464*sum(a['mean_seconds'] for a in arms.values())/3600)


def engineering_gate(root, tasks, data, call_timeout, startup_timeout):
    records = [completed(root, task, data) for task in tasks]
    if any(record is None for record in records):
        return False
    metrics = pilot_metrics(records)
    resource_passed = all(
        math.isfinite(r['elapsed_seconds']) and 0 < r['elapsed_seconds'] <= call_timeout
        and r['first_output_seconds'] is not None
        and 0 <= r['first_output_seconds'] <= r['elapsed_seconds']
        and r['memory_free_after_bytes'] > 0
        and 0 < read(root/f"session-{r['job']}.json")['start_seconds'] <= startup_timeout
        for r in records
    )
    short_forced = metrics['arms']['short']['forced'] == 6
    result = dict(**metrics, resource_passed=resource_passed, all_short_forced=short_forced,
                  passed=metrics['mechanics_passed'] and resource_passed and short_forced,
                  call_ids=[t['call_id'] for t in tasks])
    atomic(root/'engineering-gate.json', result)
    if not result['passed']:
        atomic(root/'status.json', dict(complete=False, completed=len(tasks), reason='engineering_gate_failed'))
        raise RuntimeError('Integrated engineering gate failed; preserve this run for review')
    return True


def can_start(deadline, now, call_timeout):
    return deadline - now >= call_timeout + 30
