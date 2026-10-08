"""Bounded decode attribution; profiler times are diagnostic, not latency benchmarks."""
import argparse, hashlib, json, random, sys, types
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'code'))
import benchmark as bench
import torch
lib=bench.lib

def main():
    p=argparse.ArgumentParser(description=__doc__)
    lib.add_common_args(p,default_reps=3,default_warmup=2)
    a=p.parse_args(); lib.prepare_runtime(a)
    out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    data={'manifest':lib.base_manifest(a,'decode_profile'),'completed':False,'cells':[],
          'protocol':{'batches':[1,64],'context':2048,'profile_reps':a.reps,'warmup':a.warmup,
                      'same_width_cache':True,'prefill_excluded':True,'record_shapes':False,
                      'profile_memory':False,'with_stack':False,'flush_l2':True}}
    def save():
        tmp=out.with_suffix('.tmp'); tmp.write_text(json.dumps(data,indent=2)+'\n'); tmp.replace(out)
    data['clock_ramp']=lib.clock_ramp(a.clock_ramp_s)
    data['clock_guard']=lib.wait_for_sm_clock(a.min_sm_clock_mhz); save()
    if a.strict_clock and not data['clock_guard'].get('ok'): raise RuntimeError('clock guard')
    model,tok,info=bench.build_worker.build_worker('large',lib.dtype_of(a)); data['worker']=info
    layers=model.model.layers
    with torch.inference_mode():
        probe=tok('The capital of France is',return_tensors='pt')['input_ids'].cuda()
        ref=model(input_ids=probe,use_cache=False,logits_to_keep=1).logits.clone()
        for layer in layers:
            layer.mlp.forward=types.MethodType(bench.sliced_forward,layer.mlp)
        def select(key):
            for layer,w in zip(layers,lib.preset_widths(key)): layer.mlp.active_width=w
        select('large')
        actual=model(input_ids=probe,use_cache=False,logits_to_keep=1).logits
        data['large_patch_max_logit_difference']=(ref-actual).abs().max().item()
        assert data['large_patch_max_logit_difference']==0
        del probe,ref,actual
        # Wrap whole module calls: includes functional FFN operations and attention projections/cache.
        for layer in layers:
            for name,category in [('mlp','FFN'),('self_attn','ATTENTION')]:
                mod=getattr(layer,name); original=mod.forward
                def wrapped(*args,_original=original,_category=category,**kwargs):
                    with torch.profiler.record_function('BUCKET::'+_category):
                        return _original(*args,**kwargs)
                mod.forward=wrapped
        prompt,digest=lib.build_prompt_ids(tok,2048); prompt=prompt.cuda()
        continuation=lib.next_token_id(tok).cuda(); flusher=lib.L2Flusher(a.flush_mb,True,'cuda')
        rng=random.Random(a.seed)
        for batch in [1,64]:
            cell={'batch':batch,'context':2048,'prompt_sha256':digest,'profiles':[]};data['cells'].append(cell);save()
            ids=prompt.repeat(batch,1).contiguous(); next_ids=continuation.repeat(batch,1)
            def prepare(key):
                select(key); cache=None
                for offset in range(0,2048,256):
                    result=model(input_ids=ids[:,offset:offset+256],past_key_values=cache,use_cache=True,logits_to_keep=1)
                    cache=result.past_key_values;del result
                torch.cuda.synchronize();return cache
            def step(cache):
                return model(input_ids=next_ids,past_key_values=cache,use_cache=True,logits_to_keep=1)
            for _ in range(a.warmup):
                for key in ['large','small']:
                    cache=prepare(key); result=step(cache);torch.cuda.synchronize();del result,cache
            # Check latency without an active profiler; annotations remain enabled.
            cell['unprofiled_samples']={'large':[],'small':[]}
            timer=lib.Timer()
            for rep in range(3):
                order=['large','small'];rng.shuffle(order)
                for key in order:
                    cache=prepare(key);flusher.flush()
                    result,wall,gpu=timer.time(lambda:step(cache))
                    cell['unprofiled_samples'][key].append({'rep':rep,'wall_ms':wall,'gpu_ms':gpu})
                    del result,cache
            # Discard first capture to initialize CUPTI/profiler machinery.
            cache=prepare('large');flusher.flush();torch.cuda.synchronize()
            with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA]) as startup:
                result=step(cache);torch.cuda.synchronize()
            del result,cache,startup
            save()
            for rep in range(a.reps):
                order=['large','small'];rng.shuffle(order)
                for key in order:
                    print(f'PROFILE B{batch} {key} rep{rep}',flush=True)
                    cache=prepare(key);flusher.flush();torch.cuda.synchronize()
                    with torch.profiler.profile(activities=[torch.profiler.ProfilerActivity.CPU,torch.profiler.ProfilerActivity.CUDA],record_shapes=False,profile_memory=False,with_stack=False) as prof:
                        with torch.profiler.record_function('DECODE_STEP'):
                            result=step(cache)
                        torch.cuda.synchronize()
                    trace=out.parent/f'{out.stem}-B{batch}-{key}-r{rep}.trace.json'
                    prof.export_chrome_trace(str(trace))
                    events=prof.events()
                    buckets={}
                    for cat in ['FFN','ATTENTION']:
                        matching=[e for e in events if e.name=='BUCKET::'+cat and e.device_type==torch.autograd.DeviceType.CPU]
                        assert len(matching)==len(layers),(cat,len(matching),len(layers))
                        buckets[cat]={'device_ms':sum(e.device_time_total for e in matching)/1000,
                                      'cpu_ms':sum(e.cpu_time_total for e in matching)/1000,'calls':len(matching)}
                    ops=sorted([{'name':e.key,'self_device_ms':e.self_device_time_total/1000,'self_cpu_ms':e.self_cpu_time_total/1000,'calls':e.count} for e in prof.key_averages()],key=lambda x:x['self_device_ms'],reverse=True)
                    raw=json.loads(trace.read_text())['traceEvents']
                    gpu=[e for e in raw if e.get('ph')=='X' and e.get('cat') in ['kernel','gpu_memcpy','gpu_memset']]
                    intervals=sorted((e['ts'],e['ts']+e['dur']) for e in gpu)
                    union=0; start=end=None
                    for lo,hi in intervals:
                        if end is None:start,end=lo,hi
                        elif lo<=end:end=max(end,hi)
                        else:union+=end-start;start,end=lo,hi
                    if end is not None:union+=end-start
                    span=(max(hi for lo,hi in intervals)-min(lo for lo,hi in intervals)) if intervals else 0
                    cell['profiles'].append({'width':key,'rep':rep,'buckets':buckets,'gpu_activity_sum_ms':sum(e['dur'] for e in gpu)/1000,'gpu_activity_union_ms':union/1000,'gpu_activity_span_ms':span/1000,'gpu_gap_ms':(span-union)/1000,'gpu_event_count':len(gpu),'trace':trace.name,'top_ops':ops[:25]})
                    save();del result,cache,prof,events,raw
    data['completed']=True;data['script_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();data['clocks_at_end']=lib.clocks_snapshot();save();print('PROFILE COMPLETE',flush=True)
if __name__=='__main__':main()
