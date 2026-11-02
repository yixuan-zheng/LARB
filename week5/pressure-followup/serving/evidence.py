"""Snapshot executed sources and runtime before generation."""
import hashlib,importlib.metadata,json,os,platform,subprocess
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[2]
def snapshot(root):
 lock=json.loads((HERE/'source-lock.json').read_text())
 for name,digest in lock.items():
  source=REPO/name;data=source.read_bytes();assert hashlib.sha256(data).hexdigest()==digest,name
  target=root/'sources'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(data)
 (root/'source-lock.json').write_text(json.dumps(lock,indent=2)+'\n')
 spec=json.loads((HERE/'spec.json').read_text());manifest=dict(job=os.environ['SLURM_JOB_ID'],python=platform.python_version(),versions={name:importlib.metadata.version(name) for name in ['vllm','torch','transformers','aiohttp','fastapi','uvicorn']},model=os.environ['BUDGET_MODEL_PATH'],model_revision=spec['model_revision'],source_lock_sha256=hashlib.sha256((HERE/'source-lock.json').read_bytes()).hexdigest(),gpu=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv'],text=True))
 (root/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
