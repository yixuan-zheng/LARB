"""Stage 2: force </think> at a token boundary inside one generate call."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import time
from baseline import boxed
from budget_control import BudgetState

MODEL_REV = '1cfa9a7208912126459214e8b04321603b3df60c'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--baseline', default='results/job-6303281')
    p.add_argument('--budget', type=int, default=512)
    p.add_argument('--answer-cap', type=int, default=2048)
    p.add_argument('--transition', choices=['bare', 'cue'], default='bare')
    p.add_argument('--indices', default='0,1,2,3,4,5,6,7,8,9')
    args = p.parse_args()
    indices = [int(x) for x in args.indices.split(',')]
    assert len(set(indices)) == len(indices) and all(0 <= i < 10 for i in indices)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    for name in ['interrupt_probe.py', 'budget_control.py', 'baseline.py']:
        shutil.copy2(Path(__file__).with_name(name), out / ('executed-' + name))
    baseline = Path(args.baseline)
    rows = json.loads((baseline/'problems.json').read_text())
    originals = [json.loads(line) for line in (baseline/'requests.jsonl').read_text().splitlines()]
    baseline_manifest = json.loads((baseline/'manifest.json').read_text())
    assert baseline_manifest['completed'] and len(rows) == len(originals) == 10
    assert baseline_manifest['model_revision'] == MODEL_REV
    (out/'problems.json').write_text(json.dumps(rows, indent=2))
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, AutoTokenizer, LogitsProcessor, StoppingCriteria, set_seed
    from huggingface_hub import snapshot_download
    torch.set_num_threads(4)
    path = snapshot_download('Qwen/Qwen3-4B', revision=MODEL_REV, local_files_only=True)
    tok = AutoTokenizer.from_pretrained(path)
    model = AutoModelForCausalLM.from_pretrained(path, dtype=torch.bfloat16, attn_implementation='sdpa').to('cuda').eval()
    close = tok.convert_tokens_to_ids('</think>')
    opening = tok.convert_tokens_to_ids('<think>')
    assert close != opening and close != tok.unk_token_id
    eos = model.generation_config.eos_token_id
    eos_ids = eos if isinstance(eos, list) else [eos]
    transition_text = '</think>' if args.transition == 'bare' else '\n\nI will stop checking and give the final answer now.\n</think>\n\n'
    transition_ids = tok.encode(transition_text, add_special_tokens=False)
    assert transition_ids.count(close) == 1 and close not in eos_ids
    settings = dict(do_sample=True, temperature=0.6, top_p=0.95, top_k=20)
    manifest = dict(completed=False, model='Qwen/Qwen3-4B', model_revision=MODEL_REV,
        dataset_revision=baseline_manifest['dataset_revision'], budget=args.budget, answer_cap=args.answer_cap,
        budget_definition='generated tokens before first closing marker, including opening marker and whitespace; same count convention as Stage 1',
        method=('force only </think>' if args.transition == 'bare' else 'force a short finalization cue, </think>, and newlines') + '; same generate call and KV cache; no restart or prefix replay',
        settings=settings, seed_base=6222, gpu=torch.cuda.get_device_name(), torch=torch.__version__,
        indices=indices, transition=args.transition, transition_text=transition_text, transition_ids=transition_ids,
        transformers=transformers.__version__, job_id=os.getenv('SLURM_JOB_ID'),
        timing='synchronized generation wall time; per-token observation adds CPU/GPU synchronization overhead',
        baseline=baseline_manifest, source_hashes={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in out.glob('executed-*.py')})
    def save():
        (out/'manifest.json').write_text(json.dumps(manifest, indent=2))
    save()
    def inputs(prompt):
        rendered = tok.apply_chat_template([dict(role='user', content=prompt)], tokenize=False,
            add_generation_prompt=True, enable_thinking=True)
        return rendered, tok(rendered, return_tensors='pt').to('cuda')
    _, warm = inputs('What is 2 + 2?')
    with torch.inference_mode():
        model.generate(**warm, max_new_tokens=16, do_sample=False)
    torch.cuda.synchronize()
    for i in indices:
        row, original = rows[i], originals[i]
        assert row == original['problem']
        rendered, inp = inputs(original['prompt'])
        assert rendered == original['rendered_prompt']
        state = BudgetState(args.budget, args.answer_cap, close, opening)
        events = {}
        forced = []
        pending = []
        class ForceClose(LogitsProcessor):
            def __call__(self, input_ids, scores):
                if not forced and state.should_force:
                    events['trigger_seconds'] = time.perf_counter() - start
                    pending.extend(transition_ids)
                if pending:
                    forced.append(state.count)
                    next_token = pending.pop(0)
                    scores.fill_(-float('inf'))
                    scores[:, next_token] = 0
                return scores
        class Observe(StoppingCriteria):
            def __call__(self, input_ids, scores, **kwargs):
                token = input_ids[0, -1].item()
                had_close = state.close_index is not None
                stop = state.observe(token)
                now = time.perf_counter() - start
                if not had_close and state.close_index is not None:
                    events['close_seconds'] = now
                if state.answer_tokens == 1:
                    events['first_post_close_token_seconds'] = now
                return torch.tensor([stop], device=input_ids.device)
        set_seed(6222+i)
        torch.cuda.reset_peak_memory_stats()
        torch.cuda.synchronize()
        start = time.perf_counter()
        with torch.inference_mode():
            generated = model.generate(**inp, **settings,
                max_new_tokens=args.budget+len(transition_ids)+args.answer_cap,
                logits_processor=[ForceClose()], stopping_criteria=[Observe()])
        torch.cuda.synchronize()
        elapsed = time.perf_counter()-start
        ids = generated[0, inp.input_ids.shape[1]:].tolist()
        assert state.count == len(ids)
        boundary = state.close_index
        final = tok.decode(ids[boundary+1:], skip_special_tokens=True) if boundary is not None else ''
        answer = boxed(final)
        normalize = lambda x: ''.join(x.split()) if x is not None else None
        reason = 'eos' if ids[-1] in eos_ids else ('answer_cap' if boundary is not None else 'total_cap')
        prefix_len = forced[0] if forced else (boundary if boundary is not None else len(ids))
        record = dict(index=i, seed=6222+i, problem=row, prompt=original['prompt'], rendered_prompt=rendered,
            thinking_budget=args.budget, forced_positions=forced, natural_close=not forced and boundary is not None,
            token_ids=ids, thinking_tokens=boundary, answer_tokens=state.answer_tokens,
            generated_tokens=len(ids), thinking_reopened=state.reopened,
            transition=args.transition, model_thinking_tokens=prefix_len,
            injected_token_count=len(forced),
            prefix_matches_stage1=ids[:prefix_len]==original['token_ids'][:prefix_len],
            final_answer=final, extracted_answer=answer, reference=str(row['answer']),
            exact_match=normalize(answer)==normalize(str(row['answer'])),
            finish_reason=reason, elapsed_seconds=elapsed, events=events,
            post_close_seconds=elapsed-events['close_seconds'] if 'close_seconds' in events else None,
            peak_allocated_bytes=torch.cuda.max_memory_allocated(),
            raw_output=tok.decode(ids, skip_special_tokens=False))
        with (out/'requests.jsonl').open('a') as f:
            f.write(json.dumps(record)+'\n')
        print(json.dumps({k:record[k] for k in ['index','thinking_tokens','answer_tokens','forced_positions','prefix_matches_stage1','exact_match','finish_reason','elapsed_seconds']}), flush=True)
    manifest['completed'] = True
    save()


if __name__ == '__main__':
    main()
