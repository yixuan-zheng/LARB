"""Elicit a concrete operation before recording the continuation decision."""
import argparse
import hashlib
import json
import re
import time
from pathlib import Path

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate_step

PROMPT = """The model has reasoned for 4096 tokens. Decide whether the given excerpt
shows a concrete reason to continue on this route. If the answer already
follows from the excerpt, give the result and end with READY. Otherwise name
one unmet requirement in the question, quote a short exact premise from the
excerpt, and actually perform one small calculation, correction, or deduction
that advances that requirement. A suggestion to try something is insufficient.
Do not invent missing premises or restart the solution.
Use four short lines. Put the quote on its own line as Evidence: "exact quote".
Keep the entire response under 96 tokens. End with a line containing only one
of READY, STEP, or INSUFFICIENT. Use STEP only after performing the operation.
"""


def classify(response, excerpt):
    lines = [line.strip() for line in response.strip().splitlines() if line.strip()]
    if not lines or lines[-1] not in {'READY', 'STEP', 'INSUFFICIENT'}:
        return 'INSUFFICIENT'
    if lines[-1] == 'STEP':
        evidence = re.search(r'^Evidence:\s*["“](.+?)["”]\s*$', response, re.M)
        if not evidence or evidence[1] not in excerpt or len(lines) < 4:
            return 'INSUFFICIENT'
    return lines[-1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', type=Path)
    parser.add_argument('packets', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    model, tokenizer = load(str(args.model))

    def predict(packet):
        message = f"{PROMPT}\nQuestion:\n{packet['question']}\nPrefix excerpt:\n{packet['prefix']}"
        text = tokenizer.apply_chat_template(
            [{'role': 'user', 'content': message}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        tokens = tokenizer.encode(text, add_special_tokens=False)
        started = time.perf_counter()
        output = []
        for token, _ in generate_step(mx.array(tokens), model, max_tokens=96):
            output.append(token)
            if token in tokenizer.eos_token_ids:
                break
        elapsed = time.perf_counter() - started
        response = tokenizer.decode(output, skip_special_tokens=True)
        return dict(case_id=packet['case_id'], decision=classify(response, packet['prefix']),
                    response=response, input_tokens=len(tokens), output_tokens=len(output), seconds=elapsed)

    predict(dict(case_id='warmup', question='Compute 2 plus 2.', prefix='Add the two integers.'))
    with args.output.open('x') as output:
        for packet in json.loads(args.packets.read_text()):
            output.write(json.dumps(predict(packet), ensure_ascii=False) + '\n')
            output.flush()
    args.output.with_suffix('.sha256').write_text(hashlib.sha256(args.output.read_bytes()).hexdigest() + '\n')


if __name__ == '__main__':
    main()
