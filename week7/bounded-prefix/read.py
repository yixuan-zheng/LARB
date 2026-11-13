"""Run one bounded, local reader call per anonymized packet."""
import argparse
import hashlib
import json
import time
from pathlib import Path

import mlx.core as mx
from mlx_lm import load
from mlx_lm.generate import generate_step

INSTRUCTIONS = """Forecast two answers from a separate Qwen3-4B reasoning model that is
still thinking at 4096 tokens. One branch must answer immediately; the other
can continue thinking up to 8192 tokens before answering. Predict the joint
correctness outcome. Use any supplied excerpt to look for a concrete step
that could change correctness, evidence the answer is ready, or a stalled
derivation. With no excerpt, use the question alone. Evaluate the two branch
outcomes, not your own ability to solve the problem.
A = both wrong
B = immediate wrong, continued correct
C = immediate correct, continued wrong
D = both correct
Output one uppercase letter first, then a newline and a short evidence note.
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('model', type=Path)
    parser.add_argument('packets', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    model, tokenizer = load(str(args.model))
    labels = [tokenizer.encode(label, add_special_tokens=False) for label in 'ABCD']
    assert all(len(ids) == 1 for ids in labels)
    label_ids = mx.array([ids[0] for ids in labels])

    def sample_first(logprobs):
        return label_ids[mx.argmax(logprobs[..., label_ids], axis=-1)]

    def read_one(packet):
        message = f"{INSTRUCTIONS}\nQuestion:\n{packet['question']}\nPrefix excerpt:\n{packet['prefix']}"
        prompt = tokenizer.apply_chat_template(
            [{'role': 'user', 'content': message}], tokenize=False,
            add_generation_prompt=True, enable_thinking=False,
        )
        token_ids = tokenizer.encode(prompt, add_special_tokens=False)
        start = time.perf_counter()
        forecast = None
        generated = []
        sampler_calls = 0

        def sample(logprobs):
            nonlocal sampler_calls
            sampler_calls += 1
            return sample_first(logprobs) if sampler_calls == 1 else mx.argmax(logprobs, axis=-1)

        for token, logprobs in generate_step(mx.array(token_ids), model, max_tokens=96, sampler=sample):
            if forecast is None:
                forecast = mx.softmax(logprobs[label_ids].astype(mx.float32)).tolist()
            generated.append(token)
            if token in tokenizer.eos_token_ids:
                break
        return dict(case_id=packet['case_id'], probabilities=forecast, input_tokens=len(token_ids),
                    output_tokens=len(generated), seconds=time.perf_counter() - start,
                    response=tokenizer.decode(generated, skip_special_tokens=True))

    packets = json.loads(args.packets.read_text())
    read_one(dict(case_id='warmup', question='Compute 2 plus 2.', prefix='Add the two integers.'))
    with args.output.open('x') as output:
        for index, packet in enumerate(packets, 1):
            output.write(json.dumps(read_one(packet), ensure_ascii=False) + '\n')
            output.flush()
            if index % 10 == 0 or index == len(packets):
                print(f'{index}/{len(packets)}', flush=True)
    args.output.with_suffix('.sha256').write_text(hashlib.sha256(args.output.read_bytes()).hexdigest() + '\n')


if __name__ == '__main__':
    main()
