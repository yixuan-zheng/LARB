"""Stage 1 only: unmodified, sequential Qwen3 thinking on ten MATH-500 items."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import time


def boxed(text):
    start = text.rfind('\\boxed{')
    if start < 0:
        return None
    start += len('\\boxed{')
    depth = 1
    for end in range(start, len(text)):
        depth += (text[end] == '{') - (text[end] == '}')
        if depth == 0:
            return text[start:end]
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    args = p.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    import torch
    import transformers
    from huggingface_hub import HfApi, snapshot_download, hf_hub_download
    from transformers import AutoTokenizer, AutoModelForCausalLM, set_seed
    api = HfApi()
    model_id = 'Qwen/Qwen3-4B'
    dataset_id = 'HuggingFaceH4/MATH-500'
    mr = api.model_info(model_id).sha
    dr = api.dataset_info(dataset_id).sha
    files = api.list_repo_files(dataset_id, repo_type='dataset', revision=dr)
    assert 'test.jsonl' in files, files
    data_path = hf_hub_download(dataset_id, 'test.jsonl', repo_type='dataset', revision=dr)
    rows = [json.loads(line) for line in Path(data_path).read_text().splitlines() if line.strip()][:10]
    (out / 'problems.json').write_text(json.dumps(rows, indent=2))
    path = snapshot_download(model_id, revision=mr, ignore_patterns=['*.gguf', '*.bin'])
    tok = AutoTokenizer.from_pretrained(path)
    torch.set_num_threads(4)
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda').eval()
    settings = dict(do_sample=True, temperature=0.6, top_p=0.95, top_k=20, max_new_tokens=16384)
    manifest = dict(model=model_id, model_revision=mr, dataset=dataset_id, dataset_revision=dr,
        selection='first 10 rows in the pinned dataset; development smoke test',
        problems_sha256=hashlib.sha256((out/'problems.json').read_bytes()).hexdigest(),
        settings=settings, enable_thinking=True, seed_base=6222,
        gpu=torch.cuda.get_device_name(), torch=torch.__version__, transformers=transformers.__version__,
        python=platform.python_version(), job_id=os.getenv('SLURM_JOB_ID'),
        cuda=torch.version.cuda, timing='CUDA-synchronized generate wall time; excludes tokenization, load, and warmup',
        scoring='Exact boxed-answer match after whitespace removal; manually review mismatches', completed=False)
    def save_manifest():
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    save_manifest()
    def inputs(prompt):
        text = tok.apply_chat_template([dict(role='user', content=prompt)], tokenize=False,
            add_generation_prompt=True, enable_thinking=True)
        return text, tok(text, return_tensors='pt').to('cuda')
    _, warm = inputs('What is 2 + 2?')
    with torch.inference_mode():
        model.generate(**warm, max_new_tokens=16, do_sample=False)
    torch.cuda.synchronize()
    close = tok.convert_tokens_to_ids('</think>')
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    for i, row in enumerate(rows):
        prompt = row['problem'] + '\nPlease put your final answer within \\boxed{}.'
        rendered, inp = inputs(prompt)
        set_seed(6222+i)
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        begin = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**inp, **settings)
        torch.cuda.synchronize()
        elapsed = time.perf_counter()-begin
        ids = generated[0, inp.input_ids.shape[1]:].tolist()
        boundary = ids.index(close) if close in ids else None
        final = tok.decode(ids[boundary+1:], skip_special_tokens=True) if boundary is not None else ''
        answer = boxed(final)
        reference = str(row['answer'])
        normalize = lambda x: ''.join(x.split()) if x is not None else None
        record = dict(index=i, problem=row, seed=6222+i, prompt=prompt, rendered_prompt=rendered,
            input_tokens=inp.input_ids.shape[1], generated_tokens=len(ids), token_ids=ids,
            thinking_tokens=boundary, answer_tokens=(len(ids)-boundary-1 if boundary is not None else None),
            thinking_closed=boundary is not None, final_answer=final, extracted_answer=answer,
            reference=reference, exact_match=normalize(answer)==normalize(reference),
            raw_output=tok.decode(ids, skip_special_tokens=False), elapsed_seconds=elapsed,
            generated_tokens_per_second=len(ids)/elapsed,
            finish_reason='eos' if ids[-1] in eos_ids else 'safety_cap',
            peak_allocated_bytes=torch.cuda.max_memory_allocated())
        with (out/'requests.jsonl').open('a') as f:
            f.write(json.dumps(record)+'\n')
        print(json.dumps({k:record[k] for k in ['index','thinking_tokens','generated_tokens','elapsed_seconds','exact_match','finish_reason']}), flush=True)
    manifest['completed'] = True
    save_manifest()


if __name__ == '__main__':
    main()
