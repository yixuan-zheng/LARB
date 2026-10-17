import sys,os,pathlib,json,time,collections,hashlib
from datasets import load_from_disk
from areal.api.cli_args import load_expr_config,vLLMConfig
from tir_workflow import TIRGRPOConfig
from areal.engine import RemotevLLMEngine
from areal.infra import LocalScheduler
from profile_workflow import record
import tools_profile

def events():
 return [json.loads(l) for p in pathlib.Path(os.environ['PROFILE_DIR']).glob('events-*.jsonl') for l in p.read_text().splitlines() if l.strip()]
if __name__=='__main__':
 config,_=load_expr_config(sys.argv[1:],TIRGRPOConfig)
 config.cluster.n_gpus_per_node=1;config.rollout.max_head_offpolicyness=int(1e12)
 root=pathlib.Path(__file__).parent
 raw=load_from_disk(str(root/'data-train'))
 def task(i):
  import copy
  d=dict(raw[i]);d['messages']=copy.deepcopy(d['messages'])
  d['messages'][-1]['content']+='\nBefore giving the answer, you must check your arithmetic using the calculator tool. Call it exactly like <calculator>15 + 27</calculator>, with the expression for this problem. Wait for its output, then continue your reasoning. Use the calculator again if another calculation is needed. Do not write Python. End with the final numeric answer inside \\boxed{}.'
  d['answer']=d['answer'].split('####')[-1].strip();d['source_id']=i
  return d
 manifests=dict(preflight=[task(i) for i in range(4)],comparison=[task(i) for i in range(16,32)])
 pathlib.Path(os.environ['PROFILE_DIR'],'manifest.json').write_text(json.dumps(manifests,indent=2))
 scheduler=LocalScheduler(exp_config=config);roll=RemotevLLMEngine.as_controller(config.rollout,scheduler)
 kwargs=dict(reward_fn='examples.tir.train_tir.math_reward_fn',gconfig=config.gconfig,tokenizer=config.tokenizer_path,tir_config=config.tir,enable_thinking=False)
 def run(phase,policy,capacity,data,filtered):
  record('phase_start',phase=phase,policy=policy,capacity=capacity,groups=len(data),filtered=filtered)
  start=time.perf_counter()
  result=roll.rollout_batch(data=data,workflow='tir_gate_workflow.GatedTIRWorkflow',workflow_kwargs=dict(kwargs,phase=phase,slot_policy=policy,capacity=capacity),group_size=4,should_accept_fn='tir_gate_workflow.mixed_group' if filtered else None)
  record('phase_end',phase=phase,seconds=time.perf_counter()-start,returned_groups=len(result))
  rr=[r for r in events() if r['event']=='gate_episode_end' and r['phase']==phase]
  groups=collections.defaultdict(list)
  for r in rr:groups[r['task_id']].append(r['reward'])
  assert len(rr)==len(data)*4,(phase,len(rr))
  assert len(groups)==len(data) and all(len(v)==4 for v in groups.values())
  mixed=sum(len(set(v))>1 for v in groups.values())
  if filtered:assert len(result)==mixed,(phase,len(result),mixed)
  record('phase_verified',phase=phase,episodes=len(rr),mixed_groups=mixed)
 record('experiment_start',fixed_policy=True,seed=617)
 try:
  roll.initialize(role='eval-rollout',server_args=vLLMConfig.build_args(vllm_config=config.vllm,tp_size=1,pp_size=1))
  run('preflight','fifo',16,manifests['preflight'],False)
  rr=[r for r in events() if r['event']=='gate_episode_end' and r['phase']=='preflight']
  outcomes={r['reward'] for r in rr}
  if len(outcomes)<2:record('stop',reason='preflight lacks reward variation; no comparison executed')
  else:
   for phase,policy,cap in [('native','native',16),('fifo16','fifo',16),('priority16','priority',16),('fifo8','fifo',8),('priority16_repeat','priority',16),('fifo16_repeat','fifo',16)]:
    run(phase,policy,cap,manifests['comparison'],True)
  record('experiment_complete')
 except BaseException as e:record('experiment_error',error=repr(e));raise
 finally:roll.destroy()
