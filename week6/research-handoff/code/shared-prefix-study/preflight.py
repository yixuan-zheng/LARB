"""Read-only source/data, runtime and model checks. Never initializes an engine."""
import argparse
import hashlib
import importlib.metadata
import importlib.util
from pathlib import Path

from protocol import HERE, REPO, read, sha, validate


def check(model=None):
    result = validate()
    questions = read(HERE/'inputs/questions.json')
    assert len(questions)==30 and len({q['stable_id'] for q in questions})==30
    assert sum(q['split']=='calibration' for q in questions)==10
    assert all(type(q['answer']) is int and 0<=q['answer']<=999 for q in questions)
    if model:
        for name,expected in read(HERE/'spec.json')['versions'].items():
            assert importlib.metadata.version(name).split('+')[0]==expected,name
        for name,expected in read(HERE/'model-files.json')['files'].items():
            file=Path(model)/name
            assert file.stat().st_size==expected['size'],name
            if 'sha256' in expected:
                assert sha(file)==expected['sha256'],name
            else:
                content=file.read_bytes()
                assert hashlib.sha1(f'blob {len(content)}\0'.encode()+content).hexdigest()==expected['git_blob']
        root=Path(importlib.util.find_spec('vllm').origin).parent
        sampler=(root/'v1/sample/sampler.py').read_text()
        assert sampler.index('raw_logprobs = self.compute_logprobs(logits)') < sampler.index('self.sample(logits, sampling_metadata)')
        assert 'return logits.log_softmax(dim=-1, dtype=torch.float32)' in sampler
        result['sampler_sha256']=sha(root/'v1/sample/sampler.py')
        result['engine_sha256']=sha(root/'v1/engine/llm_engine.py')
        from transformers import AutoTokenizer
        tokenizer=AutoTokenizer.from_pretrained(str(model),local_files_only=True)
        spec=read(HERE/'spec.json')
        cue=tokenizer.encode(spec['transition_text'],add_special_tokens=False)
        assert tokenizer.convert_tokens_to_ids('</think>') in cue
        answer=tokenizer.encode('\n\nThe final answer is \\boxed{4}.',add_special_tokens=False)
        special={tokenizer.convert_tokens_to_ids(t) for t in ['<think>','</think>','<|im_end|>']}
        assert len(answer)>5 and not set(answer)&special
        result.update(model_hashes_verified=True,cue_ids=cue,fixture_answer_tokens=len(answer))
    return result


if __name__=='__main__':
    import json
    parser=argparse.ArgumentParser()
    parser.add_argument('--model')
    print(json.dumps(check(parser.parse_args().model),indent=2))
