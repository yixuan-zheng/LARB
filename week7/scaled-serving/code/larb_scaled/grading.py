"""Boxed-answer extraction and grading.

The legacy rig used a last-box integer extractor plus Math-Verify. This module
keeps the same extraction discipline but returns a general expression string,
so the 2025-2026 pool's short expressions can be graded by Math-Verify when the
analysis environment provides it.
"""
import re

BOX_START = re.compile(r"\\boxed\s*\{")
INTEGER = re.compile(r"-?\d+")


def after_thinking(text):
    if "</think>" in text:
        return text.rsplit("</think>", 1)[-1]
    return text


def find_boxes(text):
    boxes = []
    for match in BOX_START.finditer(text):
        start = match.end()
        depth = 1
        index = start
        while index < len(text) and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        if depth == 0:
            boxes.append((match.start(), index, text[start:index - 1].strip()))
    return boxes


def extract_boxed(text):
    text = after_thinking(text or "")
    boxes = find_boxes(text)
    if not boxes:
        return dict(value=None, issue="missing_complete_box", boxes=[])
    if len(boxes) > 1 and re.fullmatch(r"[\s,$;]*", text[boxes[-2][1]:boxes[-1][0]]):
        return dict(value=None, issue="multiple_grouped_final_boxes",
                    boxes=[box[2] for box in boxes])
    return dict(value=boxes[-1][2], issue=None, boxes=[box[2] for box in boxes])


def normalise_answer(value):
    value = str(value or "").strip()
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("$", "").replace("\\,", "").replace("\\!", "")
    value = re.sub(r"\s+", "", value)
    return value


def exact_match(extracted, reference):
    a = normalise_answer(extracted)
    b = normalise_answer(reference)
    if a == b:
        return True
    if INTEGER.fullmatch(a) and INTEGER.fullmatch(b):
        return int(a) == int(b)
    return False


def math_verify_match(extracted, reference):
    try:
        from math_verify import parse, verify
    except ImportError:
        return None
    try:
        return bool(verify(parse(str(reference)), parse(str(extracted))))
    except Exception:
        return None


def grade(raw_output, reference, use_math_verify=False):
    extraction = extract_boxed(raw_output)
    if extraction["value"] is None:
        return dict(correct=False, extracted=None, issue=extraction["issue"],
                    match="missing")
    extracted = extraction["value"]
    if exact_match(extracted, reference):
        return dict(correct=True, extracted=extracted, issue=None, match="exact")
    if use_math_verify:
        result = math_verify_match(extracted, reference)
        if result is True:
            return dict(correct=True, extracted=extracted, issue=None, match="math_verify")
        if result is None:
            return dict(correct=False, extracted=extracted, issue=None,
                        match="math_verify_unavailable")
    return dict(correct=False, extracted=extracted, issue=None, match="mismatch")
