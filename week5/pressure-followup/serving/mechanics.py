"""Allocated-GPU synthetic boundary gate. No AIME grading; raw outputs retained."""
import argparse,json,os
from pathlib import Path
from analyze import completion
HERE=Path(__file__).resolve().parent

def main():
 p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);args=p.parse_args()
 if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm GPU allocation required')
 args.out.mkdir(parents=True,exist_ok=False);(args.out/'requests').mkdir();os.environ['BURST_OUT']=str(args.out.resolve())
 from evidence import snapshot
 snapshot(args.out)
 from transformers import AutoTokenizer
 from vllm import LLM,SamplingParams
 model=os.environ['BUDGET_MODEL_PATH'];tok=AutoTokenizer.from_pretrained(model,local_files_only=True);spec=json.loads((HERE/'spec.json').read_text());cue=tok.encode(spec['transition_text'],add_special_tokens=False);close=tok.convert_tokens_to_ids('</think>');eos=tok.convert_tokens_to_ids('<|im_end|>')
 (args.out/'pressure.json').write_text(json.dumps(dict(step=0,monotonic=0,active=[],waiting=[])))
 llm=LLM(model=model,generation_config='vllm',dtype='bfloat16',max_model_len=24576,max_num_seqs=2,max_num_batched_tokens=2048,gpu_memory_utilization=.8,enforce_eager=True,enable_prefix_caching=False,seed=6222,disable_log_stats=True,logits_processors=['mechanics_adapter:MechanicsProcessor'])
 records=[]
 for case,expected in [('below',4096),('late',5000)]:
  key='mechanics-'+case+'--r0';rendered=tok.apply_chat_template([dict(role='user',content='Compute8675309 times9182736 using detailed long multiplication, checking each step.')],tokenize=False,add_generation_prompt=True,enable_thinking=True)
  params=SamplingParams(temperature=.6,top_p=.95,top_k=20,seed=6222,max_tokens=8192+len(cue)+2048+1,skip_special_tokens=False,extra_args={'burst':dict(key=key,policy='fixed8k',budget=8192,cue=cue,close_id=close,eos_id=eos,answer_cap=2048)})
  output=llm.generate([{'prompt_token_ids':tok.encode(rendered,add_special_tokens=False)}],params,use_tqdm=False)[0].outputs[0]
  raw=dict(key=key,token_ids=list(output.token_ids),raw_output=output.text,complete=True,close_id=close,eos_id=eos,cue_ids=cue,synthetic_hold_until=expected)
  (args.out/'requests'/(key+'.json')).write_text(json.dumps(raw,indent=2)+'\n')
  result=completion(raw,expected);assert result['normal'],'Gate answer capped or incomplete; preserve raw evidence,do not retry automatically';records.append(dict(key=key,passed=True,expected_cue_start=expected,**result))
 (args.out/'gate.json').write_text(json.dumps(dict(passed=True,cases=records,note='Synthetic hold masks natural closure; tests in-flight state/cue boundary only,not live queue pressure or answer quality.'),indent=2)+'\n')
if __name__=='__main__':main()
