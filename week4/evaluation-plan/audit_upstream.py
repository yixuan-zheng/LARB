"""Inspect reviewed pure stopping functions from a pinned upstream source file; no imports/inference."""
import argparse
import ast
import hashlib
import json
from pathlib import Path

PIN='0d2f1b93a60e031cfc7fb43843d2b736b225960c'
EXPECTED='1d48de8bc45fb6936c9ec7ee8877b3ad75d42a90dd4feebe2a5c2a7796acbc89'
ap=argparse.ArgumentParser();ap.add_argument('--entropy-source',type=Path,required=True);args=ap.parse_args()
source=args.entropy_source.read_bytes()
assert hashlib.sha256(source).hexdigest()==EXPECTED, 'Use the exact reviewed pinned source (including trailing newline).'
tree=ast.parse(source)
allowed={'count_not_empty','eqaul_group','should_early_exit'}
functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in allowed]
assert {n.name for n in functions}==allowed
namespace={'math_equal':lambda a,b:a==b}
exec(compile(ast.Module(body=functions,type_ignores=[]),'reviewed-upstream-stopping-functions','exec'),namespace)
# Decimal-string examples need no symbolic equivalence package; the rest of the helper is unchanged.
cases=[('consistent',['1','1'],'1',[True,True],True),
       ('too_few',['1'],'1',[True],False),
       ('current_uncertain',['1','1'],'wait',[True,False],False),
       ('inconsistent',['1','2'],'2',[True,True],False),
       ('empty_answers',['',''],'',[True,True],False),
       ('earlier_uncertain',['1','1'],'1',[False,True],False)]
rows=[]
for name,answers,response,certain,expected in cases:
 actual=namespace['should_early_exit'](answers,response,['wait','hold','but','okay','no','hmm'],2,certain)
 rows.append(dict(case=name,expected_from_documented_contract=expected,actual=actual,matches_contract=actual==expected))
assert [r['case'] for r in rows if not r['matches_contract']]==['inconsistent','empty_answers','earlier_uncertain']
result=dict(audit_completed=True,upstream_contract_passed=False,pin=PIN,source_sha256=EXPECTED,
            source_url=f'https://github.com/hao-ai-lab/Dynasor/blob/{PIN}/dynasor/core/entropy.py',
            method='Only the three reviewed pure functions are evaluated. Decimal-string equality stands in for math_equal; no model/engine or complete Dynasor evaluation.',
            cases=rows,decision='Do not use this helper unmodified as a faithful consistency baseline; choose and disclose a contract-correct adaptation in 6B.')
Path(__file__).with_name('upstream-audit.json').write_text(json.dumps(result,indent=2)+'\n')
print('Audit complete: three controls pass; inconsistent, empty, and earlier-uncertain windows incorrectly return True in the pinned helper.')
