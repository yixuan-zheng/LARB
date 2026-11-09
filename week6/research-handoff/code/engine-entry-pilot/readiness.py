"""CPU readiness/source audit; optional allocated-host imports, never inference."""
import argparse,ast,hashlib,importlib.metadata,json,subprocess,sys,shutil,os
from pathlib import Path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
def main():
 p=argparse.ArgumentParser();p.add_argument('--runtime',action='store_true');args=p.parse_args()
 lock=json.loads((HERE/'source-lock.json').read_text())
 for name,digest in lock.items():
  path=REPO/name;assert hashlib.sha256(path.read_bytes()).hexdigest()==digest,name
  if path.suffix=='.py':ast.parse(path.read_text())
 subprocess.run(['bash','-n',str(HERE/'run.sbatch')],check=True)
 subprocess.run([sys.executable,'-B','-m','unittest','discover','-s',str(HERE),'-p','test_*.py'],check=True)
 if shutil.which('timeout'):
  for limit in ['170m']:subprocess.run(['timeout','--signal=TERM','--kill-after=30s',limit,'true'],check=True,timeout=10)
 if args.runtime:
  spec=json.loads((HERE/'spec.json').read_text())
  for name,version in spec['versions'].items():assert importlib.metadata.version(name)==version
  for name in ['aiohttp','fastapi','uvicorn','transformers','vllm']:__import__(name)
  os.environ.setdefault('BURST_OUT',str(HERE));__import__('pressure_adapter')
 print(json.dumps(dict(cpu='PASS',locked_files=len(lock),runtime_imports_checked=args.runtime,gpu_mechanics='NOT RUN',calibration='NOT RUN',measured_pilot='NOT RUN')))
if __name__=='__main__':main()
