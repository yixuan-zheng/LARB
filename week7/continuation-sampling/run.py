"""Sample continuations from saved token IDs on one allocated L40S."""
import argparse
import hashlib
import importlib.metadata
import os
import signal
import subprocess
import time
from pathlib import Path

from protocol import atomic, read, sha, token_hash
from study import (HERE, call_inputs, can_start, checkpoint, completed, engineering_gate,
                   finish, next_attempt, schedule, verify_release)


def timeout(seconds, action):
    signal.alarm(seconds)
    try:
        return action()
    finally:
        signal.alarm(0)


def run(args):
    deadline = time.monotonic() + args.allocation_seconds
    job = os.environ['SLURM_JOB_ID']
    release = verify_release()
    data, spec = read(HERE/'prefixes.json'), read(HERE/'spec.json')
    model = args.model.resolve()
    model_files = read(HERE/'model-files.json')
    if model.name != data['model_revision'] or model_files['revision'] != model.name:
        raise ValueError('Unexpected model snapshot revision')
    for name, expected in model_files['files'].items():
        path = model/name
        assert path.stat().st_size == expected['size'], name
        if 'sha256' in expected:
            assert sha(path) == expected['sha256'], name
        else:
            payload = path.read_bytes()
            header = f'blob {len(payload)}\0'.encode()
            assert hashlib.sha1(header+payload).hexdigest() == expected['git_blob'], name
    for package, expected in spec['versions'].items():
        assert importlib.metadata.version(package).split('+')[0] == expected, package
    import torch
    assert torch.cuda.device_count() == 1 and 'L40S' in torch.cuda.get_device_name(0)
    free, total = torch.cuda.mem_get_info()
    assert total >= spec['gpu_min_memory_gib']*1024**3
    assert free >= total*spec['engine']['gpu_memory_utilization']
    from transformers import AutoTokenizer
    from vllm import LLM, SamplingParams

    tokenizer = AutoTokenizer.from_pretrained(model, local_files_only=True)
    opening = tokenizer.convert_tokens_to_ids('<think>')
    assert tokenizer.convert_tokens_to_ids('</think>') == data['close_id']
    assert tokenizer.convert_tokens_to_ids('<|im_end|>') == data['eos_id']
    cue = tokenizer.encode(spec['transition_text'], add_special_tokens=False)
    assert cue == data['cue_ids']
    tasks = schedule(data, 'full')
    gate_tasks = schedule(data, 'pilot')
    assert tasks[:12] == gate_tasks
    gpu = subprocess.check_output(['nvidia-smi', '--query-gpu=name,memory.total,driver_version',
                                  '--format=csv,noheader'], text=True).strip()
    manifest = dict(release_sha256=release, mode='full', model=str(model),
                    model_revision=data['model_revision'], versions=spec['versions'],
                    source_job=data['source_job'], dataset=data['dataset'], gpu=gpu,
                    opening_id=opening, close_id=data['close_id'], eos_id=data['eos_id'], cue_ids=cue,
                    sampling={key: spec[key] for key in ('temperature','top_p','top_k','answer_cap','engine')},
                    tasks=tasks)
    with checkpoint(args.out, manifest):
        def gate():
            return engineering_gate(args.out, gate_tasks, data, spec['call_timeout_seconds'],
                                    spec['startup_timeout_seconds'])

        gate_path = args.out/'engineering-gate.json'
        if gate_path.exists() and not read(gate_path)['passed']:
            raise RuntimeError('Prior engineering gate failed; preserve this run for review')
        gate_passed = gate()
        pending = [task for task in tasks if completed(args.out, task, data) is None]
        if not pending:
            assert gate_passed
            atomic(args.out/'status.json', dict(complete=True, completed=len(tasks), planned=len(tasks)))
            print('All planned samples already committed.')
            return
        atomic(args.out/'status.json', dict(complete=False, completed=len(tasks)-len(pending), planned=len(tasks)))
        for task in pending:
            call_inputs(data, task, opening)
        os.environ['PREFIX_OUT'] = str(args.out.resolve())
        start = time.monotonic()
        llm = timeout(spec['startup_timeout_seconds'], lambda: LLM(
            model=str(model), generation_config='vllm', seed=spec['engine_seed'],
            logits_processors=['worker:PrefixProcessor'], logprobs_mode='raw_logprobs',
            disable_log_stats=True, **spec['engine']))
        engine = llm.llm_engine
        atomic(args.out/f'session-{job}.json', dict(gpu=gpu, start_seconds=time.monotonic()-start,
                                                   memory_before=free, memory_after=torch.cuda.mem_get_info()[0]))
        for count, task in enumerate(pending, len(tasks)-len(pending)+1):
            if not can_start(deadline, time.monotonic(), spec['call_timeout_seconds']):
                atomic(args.out/'status.json', dict(complete=False, completed=count-1, planned=len(tasks),
                                                   reason='allocation_checkpoint', gate_passed=gate_passed))
                print(f'Checkpointed after {count-1}/{len(tasks)} draws.', flush=True)
                return
            if task not in gate_tasks and not gate_passed:
                raise RuntimeError('Measurement requires a passed engineering gate')
            call_id = task['call_id']
            attempt = next_attempt(args.out, call_id, job)
            input_ids, prefix = call_inputs(data, task, opening)
            budget = task['budget']
            cap = spec['answer_cap']
            max_tokens = budget - len(prefix) + len(cue) + cap + 1
            assert len(input_ids) + max_tokens <= spec['engine']['max_model_len']
            control = dict(key=call_id, prefix=prefix, budget=budget, cue=cue, close_id=data['close_id'],
                           eos_id=data['eos_id'], answer_cap=cap)
            params = SamplingParams(temperature=spec['temperature'], top_p=spec['top_p'],
                                    top_k=spec['top_k'], seed=task['seed'], max_tokens=max_tokens,
                                    logprobs=0, skip_special_tokens=False, extra_args={'prefix_control': control})
            started = time.monotonic()
            first = None
            latest = None
            try:
                assert not engine.has_unfinished_requests()
                signal.alarm(spec['call_timeout_seconds'])
                engine.add_request(call_id, {'prompt_token_ids':input_ids}, params)
                while engine.has_unfinished_requests():
                    for output in engine.step():
                        assert output.request_id == call_id
                        assert list(output.prompt_token_ids) == input_ids
                        latest = output.outputs[0]
                        if first is None and latest.token_ids:
                            first = time.monotonic() - started
                assert latest is not None
            except BaseException as error:
                atomic(attempt, dict(task=task, job=job, status='interrupted', error=repr(error),
                                     partial_suffix=list(latest.token_ids) if latest is not None else []))
                raise
            finally:
                signal.alarm(0)
            suffix = list(latest.token_ids)
            checked = finish(data, task, prefix, suffix, cap, opening)
            full = prefix + suffix
            final = tokenizer.decode(full, skip_special_tokens=False)
            record = dict(task=task, job=job, attempt=attempt.name, input_hash=token_hash(input_ids),
                          prefix_hash=token_hash(prefix), suffix_hash=token_hash(suffix),
                          input_tokens=len(input_ids), suffix_token_ids=suffix, final_text=final.split('</think>')[-1],
                          first_output_seconds=first, elapsed_seconds=time.monotonic()-started,
                          finish_reason=latest.finish_reason, stop_reason=latest.stop_reason,
                          memory_free_after_bytes=torch.cuda.mem_get_info()[0], **checked)
            atomic(args.out/'calls'/f'{call_id}.json', record)
            atomic(attempt, dict(task=task, job=job, status='committed'))
            if count == len(gate_tasks):
                gate_passed = gate()
                assert gate_passed
                print('Integrated engineering gate passed; continuing frozen schedule.', flush=True)
            atomic(args.out/'status.json', dict(complete=False, completed=count, planned=len(tasks)))
            print(f"{call_id} {record['reason']} {len(suffix)} tokens {record['elapsed_seconds']:.2f}s", flush=True)
        assert gate_passed
        atomic(args.out/'status.json', dict(complete=True, completed=len(tasks), planned=len(tasks)))


def interrupted(signum, _):
    raise TimeoutError(f'Interrupted by signal {signum}')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--allocation-seconds', type=int, required=True)
    signal.signal(signal.SIGALRM, interrupted)
    signal.signal(signal.SIGTERM, interrupted)
    run(parser.parse_args())
