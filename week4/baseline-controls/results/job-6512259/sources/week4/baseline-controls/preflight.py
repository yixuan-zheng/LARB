"""CPU source/input/runtime/scoring gate; no model inference."""
import argparse,ast,hashlib,importlib.metadata as metadata,json,os,sys
from pathlib import Path
from execution import digest,source_path
HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1]
a=argparse.ArgumentParser();a.add_argument('--local',action='store_true');args=a.parse_args()
legacy=Path(os.environ.get('LARB_WEEK3_ROOT',REPO/'week3/larb'))
lock=json.loads((HERE/'source-lock.json').read_text())
for name,value in lock.items():
 p=source_path(REPO,legacy,name);assert digest(p)==value,name
 if p.suffix=='.py':compile(p.read_text(),name,'exec')
candidate=json.loads((HERE/'candidate-lock.json').read_text())['files'];assert all(lock[n]==v for n,v in candidate.items())
for n in ['w4_adapter.py','w4_server.py']:assert digest(HERE/n)==candidate['week4/step1/admission-control/'+n]
def functions(p):return {n.name:ast.dump(n) for n in ast.parse(p.read_text()).body if isinstance(n,ast.FunctionDef)}
new=functions(HERE/'w4_policy.py');original=functions(REPO/'week4/step1/admission-control/w4_policy.py')
for n in ['reduce_live','pressure_budget','make_control']:assert new[n]==original[n]
plan=json.loads((HERE/'plan.json').read_text());data=json.loads((HERE/'inputs/problems100.json').read_text());m=json.loads((HERE/'inputs/dataset-manifest.json').read_text())
assert digest(HERE/'inputs/problems100.json')==m['sparse_input_sha256']
assert len(data)==500 and {i for i,r in enumerate(data) if r is not None}==set(m['selected_indices']) and max(m['selected_indices'])<100
if not args.local:
 for n in ['vllm','torch','transformers']:assert metadata.version(n).split('+')[0]==plan['engine'][n]
 sys.path[:0]=[str(REPO/'week3/larb/code'),str(REPO/'week4/step1/controlled-comparison')]
 from grade_stage3 import grade_answer
 from metrics import outcome
 assert metadata.version('math-verify')=='0.9.0'
 assert grade_answer('1/2',r'\frac{1}{2}')['correct']
 assert not outcome(True,'thinking_cap',1,2)['correct_on_time']
print('PASS: locked deployment, static extension, unchanged admission/live core, exposed-only inputs'+('' if args.local else ', runtime and real CPU grader'))
