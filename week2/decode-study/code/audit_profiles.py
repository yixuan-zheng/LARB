"""Independently attribute GPU activities through Chrome trace external IDs."""
import argparse,bisect,collections,gzip,json
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);a=p.parse_args()
d=json.loads(a.input.read_text());audits=[]
for cell in d['cells']:
 for capture in cell['profiles']:
  trace=a.input.parent/capture['trace']
  if trace.exists():
   content=trace.read_text()
  else:
   with gzip.open(str(trace)+'.gz','rt') as h:content=h.read()
  es=json.loads(content)['traceEvents']
  scopes=sorted([e for e in es if e.get('cat')=='user_annotation' and e.get('name','').startswith('BUCKET::')],key=lambda e:e['ts'])
  starts=[e['ts'] for e in scopes];layer_counts=collections.Counter()
  for e in scopes:
   cat=e['name'].split('::')[1];e['_layer']=layer_counts[cat];layer_counts[cat]+=1
  lookup={}; op_lookup={}
  for e in es:
   if e.get('cat')!='cpu_op':continue
   ext=e.get('args',{}).get('External id');idx=bisect.bisect_right(starts,e['ts'])-1
   cat='OTHER';layer=None
   if idx>=0:
    scope=scopes[idx]
    if e.get('pid')==scope.get('pid') and e.get('tid')==scope.get('tid') and e['ts']+e.get('dur',0)<=scope['ts']+scope['dur']+0.01:
     cat=scope['name'].split('::')[1];layer=scope['_layer']
   lookup[ext]=(cat,layer);op_lookup[ext]=e['name']
  buckets=collections.defaultdict(float);ops=collections.defaultdict(float);counts=collections.Counter();layer_gpu=collections.defaultdict(float)
  bucket_counts=collections.Counter()
  for e in es:
   if e.get('ph')!='X' or e.get('cat') not in ['kernel','gpu_memcpy','gpu_memset']:continue
   ext=e.get('args',{}).get('External id');cat,layer=lookup.get(ext,('UNMAPPED',None));duration=e['dur']/1000
   buckets[cat]+=duration;bucket_counts[cat]+=1;ops[(cat,op_lookup.get(ext,'UNMAPPED'))]+=duration;counts[e['cat']]+=1
   if cat=='FFN':layer_gpu[layer]+=duration
  runtime=collections.defaultdict(float);runtime_counts=collections.Counter()
  for e in es:
   if e.get('ph')=='X' and e.get('cat')=='cuda_runtime':runtime[e['name']]+=e['dur']/1000;runtime_counts[e['name']]+=1
  audit={'batch':cell['batch'],'width':capture['width'],'rep':capture['rep'],'buckets_device_ms':dict(buckets),'gpu_activity_counts':dict(counts),'bucket_gpu_activity_counts':dict(bucket_counts),
   'ffn_narrowable_layers_device_ms':sum(v for k,v in layer_gpu.items() if k<10 or k>=25),
   'ffn_unchanged_layers_device_ms':sum(v for k,v in layer_gpu.items() if 10<=k<25),
   'top_bucket_ops':[{'bucket':k[0],'op':k[1],'device_ms':v} for k,v in sorted(ops.items(),key=lambda x:x[1],reverse=True)[:25]],
   'runtime':[{'name':k,'cpu_ms':v,'calls':runtime_counts[k]} for k,v in sorted(runtime.items(),key=lambda x:x[1],reverse=True)],
   'scope_counts':dict(layer_counts)}
  for cat in ['FFN','ATTENTION']:
   audit.setdefault('profiler_vs_trace_delta_ms',{})[cat]=capture['buckets'][cat]['device_ms']-buckets[cat]
  audits.append(audit)
a.input.with_name('trace_audit.json').write_text(json.dumps(audits,indent=2)+'\n')
print(json.dumps(audits,indent=2))
