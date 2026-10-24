"""Read installed package sources and optional cached tokenizer without an engine."""
import argparse
import ast
import hashlib
from importlib.metadata import distribution
import json
from pathlib import Path


def runtime():
    package = distribution('vllm')
    root = package.locate_file('vllm')
    names = ['v1/engine/async_llm.py', 'sampling_params.py', 'v1/sample/sampler.py',
             'v1/engine/logprobs.py', 'logprobs.py']
    result = dict(vllm=package.version,
        verification='CPU-only distribution metadata, file hashes and AST; no vLLM imports or engine construction', files={})
    for name in names:
        data = (root / name).read_bytes()
        classes = {n.name:[m.name for m in n.body if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef))]
                   for n in ast.parse(data).body if isinstance(n, ast.ClassDef)}
        result['files'][name] = dict(sha256=hashlib.sha256(data).hexdigest(), classes=classes)
    return result


def encoding(model_path):
    from transformers import AutoTokenizer
    tok = AutoTokenizer.from_pretrained(model_path, local_files_only=True)
    texts = dict(marker='Wait', alternative_marker='Alternatively',
                 probe_inducer='\n**Final Answer**\n\\boxed', close='</think>', eos='<|im_end|>')
    encodings = {name:tok.encode(text, add_special_tokens=False) for name, text in texts.items()}
    return dict(model='Qwen/Qwen3-4B', revision='1cfa9a7208912126459214e8b04321603b3df60c',
        mode='CPU tokenizer only; synthetic strings, no dataset and no model weights loaded',
        encodings=encodings,
        files={name:hashlib.sha256((model_path / name).read_bytes()).hexdigest()
               for name in ['tokenizer.json', 'tokenizer_config.json']},
        close_count_in_inducer=encodings['probe_inducer'].count(tok.convert_tokens_to_ids('</think>')))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--model-path', type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / 'runtime-audit.json').write_text(json.dumps(runtime(), indent=2) + '\n')
    if args.model_path:
        (args.out / 'encoding-audit.json').write_text(json.dumps(encoding(args.model_path), indent=2) + '\n')
