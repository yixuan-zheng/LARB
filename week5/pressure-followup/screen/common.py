"""Pure protocol, scheduling and integer grading; no model dependencies."""
import hashlib
import json
from pathlib import Path
import re

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]


def read(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def atomic(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)


def ranked_ids(plan):
    salt = plan['selection_salt']
    return sorted(range(1, 31), key=lambda i: (hashlib.sha256(f'{salt}:{i}'.encode()).hexdigest(), i))


def cases(plan, stage):
    ids = ranked_ids(plan)
    ids = ids[:12] if stage == 'pilot' else ids[12:] if stage == 'remainder' else []
    if not ids:
        raise ValueError(stage)
    result = []
    for block, base in enumerate(plan['seed_bases']):
        question_order = ids if block == 0 else list(reversed(ids))
        for j, qid in enumerate(question_order):
            budgets = list(plan['budgets'])
            rotation = j % len(budgets)
            budgets = budgets[rotation:] + budgets[:rotation]
            if block:
                budgets.reverse()
            for budget in budgets:
                result.append(dict(key=f'q{qid:02d}-s{base+qid}-b{budget}',
                                   id=qid, seed=base+qid, budget=budget, block=block))
    return result


def extract_integer(text):
    """Last complete boxed integer in the final phase; flag grouped final boxes."""
    text = text.split('</think>')[-1]
    boxes = []
    for match in re.finditer(r'\\boxed\s*\{', text):
        start, depth, i = match.end(), 1, match.end()
        while i < len(text) and depth:
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
            i += 1
        if depth == 0:
            boxes.append((match.start(), i, text[start:i-1].strip()))
    if not boxes:
        return dict(value=None, issue='missing_complete_box')
    if len(boxes) > 1 and re.fullmatch(r'[\s,$;]*', text[boxes[-2][1]:boxes[-1][0]]):
        return dict(value=None, issue='multiple_grouped_final_boxes')
    value = boxes[-1][2]
    if not re.fullmatch(r'\d{1,3}', value):
        return dict(value=None, issue='noncanonical_integer_box', extracted=value)
    return dict(value=int(value), issue=None)


def audit_completion(token_ids, budget, cue, close_id, eos_id, safety, answer_cap):
    """Validate the realized transition, retaining capped outcomes as failures."""
    closes = [i for i, value in enumerate(token_ids) if value == close_id]
    if not closes:
        assert budget == safety and len(token_ids) == safety + 1 and token_ids[-1] == eos_id, 'unexpected unclosed thinking'
        return dict(normal=False, finish='thinking_cap', thinking_tokens=safety,
                    answer_tokens=0, forced=False)
    assert len(closes) == 1, 'thinking closed more than once'
    close = closes[0]
    cue_at = budget < safety and token_ids[budget:budget+len(cue)] == cue
    assert close <= budget + len(cue), 'thinking exceeded its allowance'
    if close >= budget and budget < safety:
        assert cue_at, 'forced transition does not match the frozen cue'
    thinking = budget if cue_at else close
    answer_start = budget + len(cue) if cue_at else close + 1
    assert token_ids[-1] == eos_id, 'response lacks normal EOS'
    answer_tokens = len(token_ids) - answer_start - 1
    assert 0 <= answer_tokens <= answer_cap, 'answer allowance exceeded'
    capped = len(token_ids) - close - 1 > answer_cap
    return dict(normal=not capped, finish='answer_cap' if capped else 'normal',
                thinking_tokens=thinking, answer_tokens=answer_tokens, forced=cue_at)
