"""Frozen Stage 3 sweep: one request at a time, resumable per-item records."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import socket
import time
from baseline import boxed
from budget_control import BudgetState


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def atomic_json(path, obj):
    path = Path(path)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(obj, indent=2) + '\n')
    temp.replace(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--task', type=int, required=True)
    ap.add_argument('--root', default='stage3')
    args = ap.parse_args()
    root = Path(args.root)
    protocol = json.loads((root/'protocol.json').read_text())
    assert 0 <= args.task < 30
    config = protocol['configurations'][args.task % 6]
    shard = args.task // 6
    indices = list(range(shard*20, (shard+1)*20))
    rows = json.loads((root/'problems100.json').read_text())
    assert len(rows) == 100 and digest(root/'problems100.json') == protocol['problems_sha256']
    out = root/'results'/f"task-{args.task:02d}-{config['name']}"
    (out/'requests').mkdir(parents=True, exist_ok=True)
    source_hashes = {name:digest(Path(__file__).with_name(name)) for name in ['stage3_sweep.py','budget_control.py','baseline.py']}
    identity = dict(task=args.task, indices=indices, configuration=config, protocol_sha256=digest(root/'protocol.json'), source_hashes=source_hashes)
    manifest_path = out/'manifest.json'
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text())
        for key, value in identity.items():
            assert previous[key] == value, ('resume mismatch', key)
        if previous['completed']:
            print('Already complete', out, flush=True)
            return
    for name in source_hashes:
        shutil.copy2(Path(__file__).with_name(name), out/('executed-'+name))
    manifest = dict(**identity, completed=False, job_id=os.getenv('SLURM_JOB_ID'),
        array_job_id=os.getenv('SLURM_ARRAY_JOB_ID'), node=socket.gethostname(), python=platform.python_version())
    atomic_json(manifest_path, manifest)
    print('Loading', config['name'], 'indices',indices, flush=True)
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer, LogitsProcessor, StoppingCriteria, set_seed
    from huggingface_hub import snapshot_download
    torch.set_num_threads(4)
    path = snapshot_download(protocol['model'], revision=protocol['model_revision'], local_files_only=True)
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda').eval()
    close, opening = [tok.convert_tokens_to_ids(t) for t in ['</think>','<think>']]
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos,list) else [eos]
    transition_ids = tok.encode(protocol['transition_text'], add_special_tokens=False)
    assert transition_ids.count(close)==1 and close not in eos_ids
    manifest.update(torch=torch.__version__, transformers=transformers.__version__, cuda=torch.version.cuda,
        gpu=torch.cuda.get_device_name(), gpu_memory=torch.cuda.get_device_properties(0).total_memory,
        transition_ids=transition_ids, close_id=close, open_id=opening)
    atomic_json(manifest_path, manifest)
    def inputs(prompt):
        rendered = tok.apply_chat_template([dict(role='user',content=prompt)], tokenize=False,
            add_generation_prompt=True, enable_thinking=config['thinking'])
        return rendered,tok(rendered,return_tensors='pt').to('cuda')
    _,warm = inputs('What is 2 + 2?')
    with torch.inference_mode():
        model.generate(**warm, max_new_tokens=16, do_sample=False)
    torch.cuda.synchronize()
    for i in indices:
        item_path = out/'requests'/f'{i:03d}.json'
        if item_path.exists():
            old=json.loads(item_path.read_text())
            assert old['index']==i and old['configuration']==config['name']
            print('Resuming past',i,flush=True)
            continue
        row = rows[i]
        prompt = row['problem'] + '\nPlease put your final answer within \\boxed{}.'
        rendered,inp = inputs(prompt)
        if inp.input_ids.shape[1]+protocol['full_thinking_safety_cap']+protocol['answer_cap']+1 > 32768:
            raise ValueError('Prompt plus safety caps exceeds native context window')
        state = BudgetState(config['budget'] or protocol['full_thinking_safety_cap'],protocol['answer_cap'],close,opening)
        if not config['thinking']:
            state.close_index=-1
        events,forced,pending={},{},[]
        class Transition(LogitsProcessor):
            def __call__(self,input_ids,scores):
                if config['budget'] and not forced and state.should_force:
                    events['trigger_seconds']=time.perf_counter()-begin
                    pending.extend(transition_ids)
                if pending:
                    next_id=pending.pop(0)
                    forced[state.count]=next_id
                    scores.fill_(-float('inf'))
                    scores[:,next_id]=0
                return scores
        class Observer(StoppingCriteria):
            def __call__(self,input_ids,scores,**kwargs):
                token=input_ids[0,-1].item()
                was_closed=state.close_index is not None
                stop=state.observe(token)
                if not was_closed and state.close_index is not None:
                    events['close_seconds']=time.perf_counter()-begin
                if state.answer_tokens==1:
                    events['first_post_close_token_seconds']=time.perf_counter()-begin
                if config['name']=='full' and state.close_index is None and state.count>=protocol['full_thinking_safety_cap']:
                    stop=True
                return torch.tensor([stop],device=input_ids.device)
        seed=protocol['seed_base']+i
        set_seed(seed)
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        begin=time.perf_counter()
        max_new=(config['budget'] or protocol['full_thinking_safety_cap'])+len(transition_ids)+protocol['answer_cap'] if config['thinking'] else protocol['answer_cap']
        with torch.inference_mode():
            generated=model.generate(**inp,**protocol['sampling'],max_new_tokens=max_new,
                logits_processor=[Transition()],stopping_criteria=[Observer()])
        torch.cuda.synchronize()
        elapsed=time.perf_counter()-begin
        ids=generated[0,inp.input_ids.shape[1]:].tolist()
        assert state.count==len(ids)
        boundary=state.close_index
        final=tok.decode(ids[boundary+1:],skip_special_tokens=True) if boundary is not None else ''
        if ids[-1] in eos_ids:
            finish='eos'
        elif boundary is None:
            finish='thinking_cap'
        else:
            finish='answer_cap'
        if forced:
            assert list(forced)==list(range(config['budget'],config['budget']+len(transition_ids)))
            assert list(forced.values())==transition_ids
        record=dict(index=i,configuration=config['name'],seed=seed,input_tokens=inp.input_ids.shape[1],
            prompt=prompt,rendered_prompt=rendered,token_ids=ids,generated_tokens=len(ids),
            thinking_tokens=boundary if config['thinking'] else 0,
            model_thinking_tokens=(config['budget'] if forced else (boundary if boundary is not None else len(ids))) if config['thinking'] else 0,
            injected_tokens=len(forced),forced_positions=list(forced),answer_tokens=state.answer_tokens,
            thinking_reopened=state.reopened,final_answer=final,extracted_answer=boxed(final),
            reference=str(row['answer']),raw_output=tok.decode(ids,skip_special_tokens=False),
            finish_reason=finish,elapsed_seconds=elapsed,events=events,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),node=manifest['node'],
            job_id=manifest['job_id'],task=args.task)
        atomic_json(item_path,record)
        manifest['saved_requests']=len(list((out/'requests').glob('*.json')))
        atomic_json(manifest_path,manifest)
        print(json.dumps({k:record[k] for k in ['index','configuration','generated_tokens','finish_reason','elapsed_seconds']}),flush=True)
    manifest.update(completed=True,saved_requests=len(indices))
    atomic_json(manifest_path,manifest)
    print('COMPLETE',config['name'],shard,flush=True)


if __name__=='__main__':
    main()
