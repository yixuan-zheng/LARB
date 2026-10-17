import sys,pathlib
from datasets import load_from_disk
from areal import PPOTrainer
from areal.api.cli_args import load_expr_config
from tir_workflow import TIRGRPOConfig
import tools_profile_dyn  # Install the upstream-tool delimiter compatibility option.
from profile_workflow import install_consumption_observer,record
if __name__=='__main__':
 config,_=load_expr_config(sys.argv[1:],TIRGRPOConfig)
 root=pathlib.Path(__file__).parent
 train=load_from_disk(str(root/'data-train'));test=load_from_disk(str(root/'data-test')).select(range(32))
 # Upstream verifier expects a final answer, whereas GSM8K stores reasoning plus #### answer.
 def tool_task(row):
  import copy
  messages=copy.deepcopy(row['messages'])
  messages[-1]['content']+='\nBefore giving the answer, you must check your arithmetic using the calculator tool. Call it exactly like <calculator>15 + 27</calculator>, with the expression for this problem. Wait for its output, then continue your reasoning. Use the calculator again if another calculation is needed. Do not write Python. End with the final numeric answer inside \\boxed{}.'
  return {'messages':messages,'answer':row['answer'].split('####')[-1].strip()}
 train=train.map(tool_task)
 test=test.map(tool_task)
 import hashlib,json
 manifest={split:[dict(prompt_sha256=hashlib.sha256(row['messages'][0]['content'].encode()).hexdigest(),messages=row['messages'],answer=row['answer']) for row in ds] for split,ds in [('train',train),('test',test)]}
 (root/'calc-dataset-manifest.json').write_text(json.dumps(manifest,indent=2))
 install_consumption_observer()
 kwargs=dict(reward_fn='examples.tir.train_tir.math_reward_fn',gconfig=config.gconfig,tokenizer=config.tokenizer_path,tir_config=config.tir,enable_thinking=False)
 evaluation=dict(kwargs);evaluation['gconfig']=config.gconfig.new(temperature=.6)
 record('experiment_start',trial=config.trial_name,steps=config.total_train_steps,max_head_offpolicyness=config.rollout.max_head_offpolicyness)
 try:
  with PPOTrainer(config,train_dataset=train,valid_dataset=test) as trainer:
   trainer.train(workflow='tools_profile_dyn.ToolsWorkflow',workflow_kwargs=kwargs,eval_workflow='tools_profile_dyn.ToolsWorkflow',eval_workflow_kwargs=evaluation,dynamic_filter_fn='tools_profile_dyn.mixed_reward_group')
  record('experiment_complete',trial=config.trial_name)
 except BaseException as e:record('experiment_error',error=repr(e));raise
