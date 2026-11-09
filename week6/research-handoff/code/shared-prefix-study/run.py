"""One allocated-GPU engine, shared-prefix branching, immutable raw records."""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import signal as signals
import subprocess
import sys
import time

from protocol import HERE, REPO, atomic, audit, branch_seed, read, schedule, sha, signal, token_hash, validate, validate_thinking_opening


class CallTimeout(RuntimeError):
    pass


def run(args):
    assert os.environ.get('SLURM_JOB_ID'), 'Slurm allocation required'
    args.out.mkdir(parents=True, exist_ok=False)
    for name in ['calls', 'pairs']:
        (args.out/name).mkdir()
    os.environ['PREFIX_OUT'] = str(args.out.resolve())
    spec = read(HERE/'spec.json')
    status = dict(complete=False, completed_pairs=0, planned_pairs=60, engineering_calls=0, current=None)
    atomic(args.out/'status.json', status)
    atomic(args.out/'schedule.json', schedule())
    atomic(args.out/'spec.json', spec)
    atomic(args.out/'questions.json', read(HERE/'inputs/questions.json'))
    start = time.monotonic()
    try:
        verified = validate()
        for relative in read(HERE/'source-lock.json'):
            target = args.out/'sources'/relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(REPO/relative, target)
        shutil.copyfile(HERE/'source-lock.json', args.out/'source-lock.json')
        for package, version in spec['versions'].items():
            assert importlib.metadata.version(package).split('+')[0] == version
        import torch
        assert torch.cuda.is_available()
        device = torch.cuda.get_device_name(0)
        assert 'L40S' in device, f'Frozen L40S allocation required, got {device}'
        free, total = torch.cuda.mem_get_info()
        assert total >= spec['gpu_min_memory_gib']*1024**3
        assert free >= total*spec['engine']['gpu_memory_utilization']
        from transformers import AutoTokenizer
        from vllm import LLM, SamplingParams
        tokenizer = AutoTokenizer.from_pretrained(str(args.model), local_files_only=True)
        close = tokenizer.convert_tokens_to_ids('</think>')
        eos = tokenizer.convert_tokens_to_ids('<|im_end|>')
        opening = tokenizer.convert_tokens_to_ids('<think>')
        cue = tokenizer.encode(spec['transition_text'], add_special_tokens=False)
        assert cue.count(close) == 1 and eos not in cue
        atomic(args.out/'manifest.json', dict(job=os.environ['SLURM_JOB_ID'],
            source=verified, gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv'],text=True),
            versions={p:importlib.metadata.version(p) for p in spec['versions']},
            model_revision=read(HERE/'model-files.json')['revision'], model=str(args.model),
            dataset=read(HERE/'inputs/manifest.json'), cue_ids=cue, close_id=close, eos_id=eos,
            observation='raw pre-temperature pre-truncation sampled-token logprobs'))
        # Bound the initial engine load within the allocation.
        signals.alarm(spec['startup_timeout_seconds'])
        llm = LLM(model=str(args.model), generation_config='vllm', seed=spec['engine_seed'],
                  logits_processors=['worker:PrefixProcessor'], logprobs_mode='raw_logprobs',
                  disable_log_stats=True, **spec['engine'])
        signals.alarm(0)
        counter = 0

        def call(key, prompt, prefix, budget, seed, max_tokens, engineering=False, synthetic=None):
            nonlocal counter
            counter += 1
            if engineering:
                status['engineering_calls'] += 1
                assert status['engineering_calls'] <= spec['engineering_max_calls']
            status['current'] = key
            atomic(args.out/'status.json', status)
            control = dict(key=key, prefix=prefix, budget=budget, cue=cue, close_id=close,
                           eos_id=eos, answer_cap=spec['answer_cap'], synthetic=synthetic)
            params = SamplingParams(temperature=spec['temperature'], top_p=spec['top_p'],
                top_k=spec['top_k'], seed=seed, max_tokens=max_tokens, logprobs=0,
                skip_special_tokens=False, extra_args={'prefix_control':control})
            input_ids = prompt + prefix
            assert len(input_ids)+max_tokens <= spec['engine']['max_model_len']
            request_id = f'prefix-{counter}'
            begin = time.monotonic()
            record = dict(key=key, engineering=engineering, seed=seed,
                input_token_ids=input_ids, input_hash=token_hash(input_ids),
                saved_prefix_hash=token_hash(prefix), budget=budget, max_tokens=max_tokens,
                complete=False, token_ids=[], sampled_logprobs=[], raw_output='', elapsed_seconds=None,
                first_output_seconds=None)
            atomic(args.out/'calls'/f'{key}.json', record)
            latest = None
            signals.alarm(spec['call_timeout_seconds'])
            try:
                llm.llm_engine.add_request(request_id, {'prompt_token_ids':input_ids}, params)
                while llm.llm_engine.has_unfinished_requests():
                    for output in llm.llm_engine.step():
                        if output.request_id == request_id:
                            latest = output.outputs[0]
                            if record['first_output_seconds'] is None and latest.token_ids:
                                record['first_output_seconds'] = time.monotonic()-begin
                    if time.monotonic()-begin > spec['call_timeout_seconds']:
                        llm.llm_engine.abort_request([request_id])
                        raise CallTimeout(key)
                assert latest is not None
                record['complete'] = True
            finally:
                signals.alarm(0)
                if latest is not None:
                    record.update(token_ids=list(latest.token_ids), raw_output=latest.text,
                        finish_reason=latest.finish_reason, stop_reason=latest.stop_reason)
                    if latest.logprobs is not None:
                        record['sampled_logprobs'] = [v[t].logprob for t,v in zip(latest.token_ids,latest.logprobs)]
                record['elapsed_seconds'] = time.monotonic()-begin
                atomic(args.out/'calls'/f'{key}.json', record)
            assert len(record['sampled_logprobs']) == len(record['token_ids'])
            return record

        def prompt_ids(text):
            rendered = tokenizer.apply_chat_template(
                [dict(role='user',content=text+spec['prompt_suffix'])],
                tokenize=False, add_generation_prompt=True, enable_thinking=True)
            return tokenizer.encode(rendered, add_special_tokens=False)

        def pair(item, text, engineering=False, synthetic_open=False, fixture_tokens=None):
            assert engineering or (not synthetic_open and fixture_tokens is None)
            prompt = prompt_ids(text)
            synthetic = None
            if synthetic_open:
                safe_token = tokenizer.encode(' 1', add_special_tokens=False)[-1]
                assert safe_token not in [close,eos,opening]
                synthetic = dict(until=4096,token=safe_token)
            if fixture_tokens is not None:
                synthetic = dict(sequence=fixture_tokens)
            prefix = call(item['key']+'-prefix',prompt,[],8192,item['seed'],4096,engineering,synthetic)
            ids = prefix['token_ids']
            early = close in ids
            assert eos not in ids or early
            result = dict(**item, eligible=not early,
                closure_origin='controlled_fixture' if fixture_tokens is not None else 'model',
                prefix_hash=token_hash(ids),
                prompt_token_ids=prompt, prefix_token_ids=ids,
                prefix_seconds=prefix['elapsed_seconds'], prefix_tokens=len(ids),
                score=None, branches={}, complete=False)
            path = args.out/'pairs'/f"{item['key']}.json"
            atomic(path,result)
            validate_thinking_opening(ids,opening,close)
            if early:
                suffix = None
                full = ids
                if not ids or ids[-1] != eos:
                    close_at = ids.index(close)
                    remaining = spec['answer_cap']-(len(ids)-close_at-1)+1
                    suffix = call(item['key']+'-early',prompt,ids,8192,
                        branch_seed(item['seed'],'early'), max(remaining,1), engineering, synthetic)
                    full = ids+suffix['token_ids']
                validate_thinking_opening(full,opening,close)
                checked = audit(full,close,eos,cue,8192,spec['answer_cap'])
                branch = dict(token_ids=full, raw_output=tokenizer.decode(full,skip_special_tokens=False),
                    suffix_tokens=0 if suffix is None else len(suffix['token_ids']),
                    suffix_seconds=0 if suffix is None else suffix['elapsed_seconds'], **checked)
                result['branches'] = dict(short=branch,long=branch)
            else:
                assert len(ids) == 4096, 'incomplete checkpoint'
                result['score'] = signal(prefix['sampled_logprobs'],spec['signal_window'])
                atomic(path,result)
                for name in item['branch_order']:
                    budget = 4096 if name == 'short' else 8192
                    synthetic = dict(until=8192,token=safe_token) if synthetic_open and name=='long' else None
                    suffix = call(item['key']+'-'+name,prompt,ids,budget,
                        branch_seed(item['seed'],name),
                        budget-4096+len(cue)+spec['answer_cap']+1,engineering,synthetic)
                    assert suffix['input_token_ids'] == prompt+ids
                    full = ids+suffix['token_ids']
                    checked = audit(full,close,eos,cue,budget,spec['answer_cap'])
                    validate_thinking_opening(full,opening,close)
                    result['branches'][name] = dict(token_ids=full,
                        raw_output=tokenizer.decode(full,skip_special_tokens=False),
                        suffix_tokens=len(suffix['token_ids']), suffix_seconds=suffix['elapsed_seconds'],
                        input_hash=suffix['input_hash'], **checked)
                    atomic(path,result)
            result['complete'] = True
            atomic(path,result)
            return result

        gate_started = time.monotonic()
        gate = pair(dict(key='engineering-boundary',seed=6222,branch_order=['short','long']),
            'Compute 8675309 times 9182736.',True,synthetic_open=True)
        assert gate['eligible']
        for name,budget in [('short',4096),('long',8192)]:
            assert gate['branches'][name]['token_ids'][budget:budget+len(cue)] == cue
        # A prescribed transcript crosses the checkpoint during answering.
        # Every token through EOS is controlled, so model reopening is irrelevant
        # to this fixture's test of the production early-answer continuation path.
        safe_token = tokenizer.encode(' 1', add_special_tokens=False)[-1]
        answer = tokenizer.encode('\n\nThe final answer is \\boxed{4}.', add_special_tokens=False)
        assert len(answer) > 5 and not set(answer) & {close,eos,opening}
        fixture_tokens = [safe_token]*4090+[close]+answer+[eos]
        fixture = pair(dict(key='engineering-early-answer',seed=16222,branch_order=['long','short']),
            'Compute 2 plus 2.',True,fixture_tokens=fixture_tokens)
        assert not fixture['eligible'] and fixture['complete']
        assert len(fixture['prefix_token_ids']) == 4096
        assert fixture['branches']['short']['token_ids'] == fixture_tokens
        assert fixture['branches']['short']['suffix_tokens'] > 0
        assert fixture['branches']['short'] == fixture['branches']['long']
        # One unmodified sample observes actual natural closure separately.
        observed = call('engineering-natural-observation',prompt_ids('Compute 2 plus 2.'),
            [],8192,26222,4096,engineering=True)
        natural_ids = observed['token_ids']
        assert natural_ids.count(close) <= 1, 'multiple-close natural observation'
        if close in natural_ids:
            assert opening not in natural_ids[natural_ids.index(close)+1:]
            if natural_ids[-1] == eos:
                assert audit(natural_ids,close,eos,cue,8192,spec['answer_cap'])['reason'] in ['normal','answer_cap']
        for measured_gate in [gate, fixture]:
            for branch in measured_gate['branches'].values():
                assert branch['reason'] in ['normal','answer_cap']
                assert opening not in branch['token_ids'][branch['close_index']+1:]
        assert time.monotonic()-gate_started <= spec['gate_timeout_seconds']
        worker_events = [json.loads(v) for v in (args.out/'worker.jsonl').read_text().splitlines()]
        assert any(e['event']=='logprob_numeric_gate' and e['passed'] for e in worker_events)
        atomic(args.out/'gate.json',dict(passed=True, calls=status['engineering_calls'],
            boundary_prefix_hash=gate['prefix_hash'],early_answer_fixture=True,
            fixture_prefix_hash=fixture['prefix_hash'],
            natural_closure_observed=close in natural_ids,
            natural_observation_completed=natural_ids[-1]==eos,
            synthetic_reasoning=True, scope='token boundaries and numerical logprob path only'))
        measured_start = time.monotonic()
        questions = {q['id']:q for q in read(HERE/'inputs/questions.json')}
        for item in schedule():
            if time.monotonic()-measured_start > spec['measurement_timeout_seconds']-900:
                status['failure'] = 'measurement_time_cap_before_pair'
                break
            try:
                pair(item,questions[item['id']]['problem'])
                status['completed_pairs'] += 1
            except CallTimeout as exc:
                # A timeout is preserved; no retry. Keep the pair's missing branches visible.
                status.setdefault('timed_out_pairs',[]).append(item['key'])
                atomic(args.out/'pairs'/f"{item['key']}-failure.json",
                    dict(key=item['key'],failure=str(exc),complete=False))
            status['current'] = None
            atomic(args.out/'status.json',status)
            print(json.dumps(dict(pair=item['key'],completed=status['completed_pairs'])),flush=True)
            # Seal calibration before generating any evaluation question.
            if item == schedule()[19]:
                from analyze import seal_calibration
                seal_calibration(args.out)
        status['complete'] = status['completed_pairs']==60
    except BaseException as exc:
        status['failure'] = f'{type(exc).__name__}: {exc}'
        raise
    finally:
        signals.alarm(0)
        status['wall_seconds'] = time.monotonic()-start
        atomic(args.out/'status.json',status)
    if not status['complete']:
        raise RuntimeError('incomplete study; preserve all outcomes')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model',type=Path,required=True)
    parser.add_argument('--out',type=Path,required=True)
    def terminate(signum, frame):
        raise RuntimeError(f'timeout or termination signal {signum}')
    signals.signal(signals.SIGTERM,terminate)
    signals.signal(signals.SIGALRM,terminate)
    run(parser.parse_args())
