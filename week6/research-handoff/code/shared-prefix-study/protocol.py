"""CPU-only protocol checks and deterministic study schedule."""
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def read(path):
    return json.loads(Path(path).read_text())


def atomic(path, value):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n')
    temp.replace(path)


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for block in iter(lambda: handle.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def token_hash(ids):
    return hashlib.sha256(json.dumps(ids, separators=(',', ':')).encode()).hexdigest()


def branch_seed(seed, branch):
    return int.from_bytes(hashlib.sha256(f'{seed}:{branch}'.encode()).digest()[:4], 'big')


def schedule():
    questions = read(HERE / 'inputs/questions.json')
    spec = read(HERE / 'spec.json')
    rows = []
    for split in ['calibration', 'evaluation']:
        for block, base in enumerate(spec['seed_bases']):
            ordered = [q for q in questions if q['split'] == split]
            ordered.sort(key=lambda q: hashlib.sha256(('larb-prefix-v1:'+q['stable_id']).encode()).hexdigest())
            if block:
                ordered.reverse()
            for rank, q in enumerate(ordered):
                order = ['short', 'long']
                if (rank + block) % 2:
                    order.reverse()
                rows.append(dict(key=f"q{q['id']:02d}-b{block}", id=q['id'], split=split,
                                 block=block, seed=base+q['id'], branch_order=order))
    return rows


def validate():
    spec = read(HERE / 'spec.json')
    lock = read(HERE / 'source-lock.json')
    for path, expected in lock.items():
        assert sha(REPO / path) == expected, path
    rows = schedule()
    assert len(rows) == len({r['key'] for r in rows}) == 60
    assert sum(r['split'] == 'evaluation' for r in rows) == 40
    assert spec['checkpoint'] == 4096 and spec['long_budget'] == 8192
    return dict(passed=True, files=len(lock), source_lock_sha256=sha(HERE/'source-lock.json'))


def audit(ids, close, eos, cue, budget, answer_cap):
    closes = [i for i, token in enumerate(ids) if token == close]
    if not closes or len(closes) != 1:
        return dict(normal=False, reason='missing_or_multiple_close', forced=False)
    at = closes[0]
    forced = ids[budget:budget+len(cue)] == cue
    assert at < budget or forced, 'bad cue or exceeded reasoning budget'
    assert ids and ids[-1] == eos, 'missing EOS'
    capped = len(ids)-at-1 > answer_cap
    return dict(normal=not capped, reason='answer_cap' if capped else 'normal',
                forced=forced, close_index=at)


def signal(logprobs, window):
    assert len(logprobs) >= window
    values = logprobs[-window:]
    assert all(math.isfinite(v) and v <= 1e-5 for v in values)
    return sum(values)/window


class JoinedTokens:
    def __init__(self, prefix, output):
        self.prefix = prefix
        self.output = output

    def __len__(self):
        return len(self.prefix) + len(self.output)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return (self.prefix + self.output)[index]
        if index < 0:
            index += len(self)
        if index < len(self.prefix):
            return self.prefix[index]
        return self.output[index - len(self.prefix)]




def synthetic_token(fixture, position):
    """Controlled engineering tokens only; None leaves model sampling unchanged."""
    if fixture is None:
        return None
    if 'sequence' in fixture:
        sequence = fixture['sequence']
        return sequence[position] if position < len(sequence) else None
    return fixture['token'] if position < fixture['until'] else None


def validate_thinking_opening(ids, opening, close):
    """Permit an initial model-generated opener and reject later reopening."""
    positions = [i for i, token in enumerate(ids) if token == opening]
    if close in ids:
        assert not any(i > ids.index(close) for i in positions), 'thinking reopened after closure'
    assert all(i == 0 for i in positions), 'unexpected opening-think token'
