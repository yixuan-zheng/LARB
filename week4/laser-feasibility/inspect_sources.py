"""Inspect pinned upstream sources on CPU; never import upstream model scripts."""
import argparse
import ast
import contextlib
import hashlib
import io
import json
import math
from pathlib import Path
import types
from reference import Load, Parameters, budget

HERE = Path(__file__).resolve().parent


def inspect(source_dir):
    sources = json.loads((HERE / 'sources.json').read_text())
    for name, meta in sources['files'].items():
        assert hashlib.sha256((source_dir / name).read_bytes()).hexdigest() == meta['sha256'], name
    tree = ast.parse((source_dir / 'vllm-deer-qwen3.py').read_text())
    function = next(n for n in tree.body if isinstance(n, ast.FunctionDef)
                    and n.name == 'calculate_average_max_prob_from_logprobs')
    # Execute this single pinned function with a scalar math stub, without torch,
    # vLLM, model scripts, network, model weights, or GPU initialization.
    torch = types.SimpleNamespace(tensor=lambda x:x,
                exp=lambda x:types.SimpleNamespace(item=lambda:math.exp(x)))
    namespace = dict(math=math, torch=torch)
    exec(compile(ast.Module(body=[function], type_ignores=[]), '<pinned-helper>', 'exec'), namespace)
    helper = namespace[function.name]
    lp = lambda p, text:types.SimpleNamespace(logprob=math.log(p), decoded_token=text)
    cases = []
    for label, rows in [
        ('single_token', [{1:lp(.99, '</think>')}]),
        ('sampled_first_is_not_top_one', [{0:lp(.9, 'prefix')},
                                        {5:lp(.2, 'sampled'), 1:lp(.98, '</think>')}]),
        ('empty_window', [])]:
        with contextlib.redirect_stdout(io.StringIO()):
            try: observed = helper(rows)
            except Exception as error: observed = dict(exception=type(error).__name__)
        cases.append(dict(case=label, observed=observed))
    load_rows = []
    for target in [10, 2, 1]:
        for active in [0, 1, 2]:
            load = Load(Parameters(target=target))
            thresholds = [load.observe_atp(active) for _ in range(100)]
            load_rows.append(dict(target=target, active=active,
                first=thresholds[0], after_100=thresholds[-1],
                chunks_at_275_prompt_tokens=budget(275, active, load.params)))
    runtime = json.loads((HERE / 'runtime-audit.json').read_text())
    mapping = {'async_llm.py':'v1/engine/async_llm.py', 'sampling_params.py':'sampling_params.py',
               'logprobs.py':'v1/engine/logprobs.py', 'sampler.py':'v1/sample/sampler.py',
               'logprobs-core.py':'logprobs.py'}
    matches = {name:runtime['files'][path]['sha256'] == sources['files'][name]['sha256']
               for name, path in mapping.items()}
    assert all(matches.values())
    result = dict(upstream_helper_cases=cases,
        helper_limit='Single unmodified AST function, scalar exp stub rather than Torch float32; synthetic compatibility findings, not a DEER/LASER accuracy or full-system result.',
        load_sensitivity=load_rows, installed_vllm_matches_official_tag=matches,
        public_async_methods=runtime['files']['v1/engine/async_llm.py']['classes']['AsyncLLM'],
        gpu_runs=0, generated_dataset_questions=0)
    (HERE / 'source-audit.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-dir', type=Path, required=True)
    inspect(parser.parse_args().source_dir)
