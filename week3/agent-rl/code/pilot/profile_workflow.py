"""Measurement-only wrapper around AReaL's upstream multi-turn math workflow.
No admission, sampling, reward, or loss decision is changed.
"""
import hashlib,json,os,pathlib,threading,time
from examples.multi_turn_math.gsm8k_rl_mt import MultiturnRLVRWorkflow,gsm8k_reward_fn
from areal import workflow_context
from areal.experimental.openai import ArealOpenAI
from areal.utils import stats_tracker
_LOCK=threading.Lock()
def record(event,**fields):
    root=pathlib.Path(os.environ['PROFILE_DIR']);root.mkdir(parents=True,exist_ok=True)
    row={'event':event,'time':time.time(),'monotonic':time.perf_counter(),'pid':os.getpid(),**fields}
    with _LOCK:
        with (root/f'events-{os.getpid()}.jsonl').open('a') as f:f.write(json.dumps(row,default=str)+'\n')
def timed_reward(result,answer):
    start=time.perf_counter();reward=gsm8k_reward_fn(result,answer)
    record('reward',response_sha256=hashlib.sha256(str(result).encode()).hexdigest(),seconds=time.perf_counter()-start,reward=reward)
    return reward
class ProfiledWorkflow(MultiturnRLVRWorkflow):
    async def arun_episode(self,engine,data):
        ctx=workflow_context.get();prompt=data['messages'][0]['content'];key=hashlib.sha256(prompt.encode()).hexdigest()
        fields={'task_id':ctx.task_id,'sample_idx':ctx.sample_idx,'is_eval':ctx.is_eval,'prompt_sha256':key}
        start=time.perf_counter();record('workflow_start',version=engine.get_version(),**fields)
        client=ArealOpenAI(engine=engine,tokenizer=self.tokenizer,chat_template_type=self.chat_template_type)
        try:
            reward=await self.agent.run_agent(data=data,client=client)
            turns=[]
            for interaction in client._cache.values():
                interaction.metadata.update(fields)
                mr=interaction.model_response
                turns.append({'reward':interaction.reward,'original_reward':interaction.original_reward,'input_tokens':len(mr.input_tokens) if mr else None,'output_tokens':len(mr.output_tokens) if mr else None,'version_min':min(mr.output_versions) if mr and mr.output_versions else None,'version_max':max(mr.output_versions) if mr and mr.output_versions else None,'stop_reason':mr.stop_reason if mr else None,'latency':mr.latency if mr else None,'ttft':mr.ttft if mr else None,'response_sha256':hashlib.sha256(str(interaction.completion.choices[0].message.content).encode()).hexdigest() if interaction.completion else None})
            record('workflow_end',seconds=time.perf_counter()-start,reward=reward,turns=turns,end_version=engine.get_version(),**fields)
            stats_tracker.get(workflow_context.stat_scope()).scalar(reward=reward)
            client.apply_reward_discount(turn_discount=.9)
            return client.export_interactions(style=self.export_style)
        except BaseException as e:
            record('workflow_error',seconds=time.perf_counter()-start,error=repr(e),**fields);raise

def install_consumption_observer():
    from areal.infra.workflow_executor import BatchTaskDispatcher,unwrap_workflow_result
    original=BatchTaskDispatcher.active_submit_and_wait
    def observed(self,*args,**kwargs):
        start=time.perf_counter();results=original(self,*args,**kwargs)
        record('batch_consumed',seconds=time.perf_counter()-start,version=self.staleness_manager.version_provider.get_version(),task_ids=[r.task_id for x in results if (r:=unwrap_workflow_result(x)) is not None],count=len(results))
        return results
    BatchTaskDispatcher.active_submit_and_wait=observed
