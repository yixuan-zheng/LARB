"""Run with the pinned environment's Python; source inspection only."""
import hashlib
import importlib.metadata
import json
from pathlib import Path
import sysconfig

root = Path(sysconfig.get_paths()['purelib'])
selection = {
    'vllm/v1/core/sched/output.py': [(1,110),(155,175)],
    'vllm/v1/core/sched/scheduler.py': [(650,725)],
    'vllm/v1/engine/core.py': [(328,345),(380,400)],
    'vllm/v1/worker/gpu_model_runner.py': [(710,747)],
    'vllm/v1/worker/gpu_input_batch.py': [(280,301),(737,751)],
}
result = dict(vllm=importlib.metadata.version('vllm'), files={})
for name, ranges in selection.items():
    path = root/name
    lines = path.read_text().splitlines()
    result['files'][name] = dict(sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        excerpts=[dict(start=start,end=end,text='\n'.join(
            f'{i+1}: {lines[i]}' for i in range(start-1,min(end,len(lines)))))
            for start,end in ranges])
print(json.dumps(result,indent=2))
