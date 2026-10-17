import sys,time,pathlib,re,json,urllib.request
log=pathlib.Path(sys.argv[1]);output=pathlib.Path(sys.argv[2]);deadline=time.monotonic()+float(sys.argv[3] if len(sys.argv)>3 else 900)
keep={'num_requests_running','num_requests_waiting','kv_cache_usage_perc','gpu_cache_usage_perc','num_preemptions_total','prompt_tokens_total','generation_tokens_total','request_success_total'}
while time.monotonic()<deadline:
 try:
  text=log.read_text(errors='replace');match=re.search(r'--host\s+([0-9.]+)\s+--port\s+(\d+)',text)
  if match:
   url=f'http://{match.group(1)}:{match.group(2)}/metrics'
   with urllib.request.urlopen(url,timeout=2) as response:body=response.read().decode()
   metrics={}
   for line in body.splitlines():
    if not line.startswith('vllm:'):continue
    name=line.split('{')[0].split()[0].removeprefix('vllm:')
    if name in keep:metrics.setdefault(name,[]).append(float(line.split()[-1]))
   with output.open('a') as f:f.write(json.dumps({'time':time.time(),'metrics':metrics})+'\n')
 except (OSError,ValueError):pass
 time.sleep(2)
