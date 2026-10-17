"""CPU-only reconstruction and verification of the two main saved analyses."""
from pathlib import Path
import tempfile,shutil,subprocess,sys,json,math
ROOT=Path(__file__).resolve().parent
def equivalent(a,b):
 if isinstance(a,dict) and isinstance(b,dict):return a.keys()==b.keys() and all(equivalent(a[k],b[k]) for k in a)
 if isinstance(a,list) and isinstance(b,list):return len(a)==len(b) and all(equivalent(x,y) for x,y in zip(a,b))
 if isinstance(a,(int,float)) and isinstance(b,(int,float)):return math.isclose(a,b,rel_tol=1e-12,abs_tol=1e-9)
 return a==b
with tempfile.TemporaryDirectory(prefix='agent-rl-analysis-') as temp:
 tmp=Path(temp)
 for stage,old in [('pilot','agent-rl-tools'),('comparison','agent-rl-comparison')]:
  shutil.copytree(ROOT/'results'/stage,tmp/'outputs'/old)
 (tmp/'outputs/agent-rl-diagnosis').mkdir(parents=True)
 for stage in ['diagnosis','comparison']:
  completed=subprocess.run([sys.executable,str(ROOT/'code'/stage/'analyze.py')],cwd=tmp,check=True,capture_output=True,text=True)
  out=ROOT/'analysis-output'/stage;out.mkdir(parents=True,exist_ok=True)
  (out/'console.txt').write_text(completed.stdout)
  old={'diagnosis':'agent-rl-diagnosis','comparison':'agent-rl-comparison'}[stage]
  checks=['diagnosis.json','wide-training-windows.json'] if stage=='diagnosis' else ['results.json','checks.json']
  for name in checks:
   got=json.loads((tmp/'outputs'/old/name).read_text());expected=json.loads((ROOT/'results'/stage/name).read_text())
   assert equivalent(got,expected),f'Saved analysis mismatch: {stage}/{name}'
  for p in (tmp/'outputs'/old).glob('*'):
   if p.is_file() and p.suffix in ['.json','.csv']:shutil.copy2(p,out/p.name)
  print(f'PASS: {stage} analysis matches saved results')
print('Regenerated outputs: analysis-output/ (no GPU work performed)')
