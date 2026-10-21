"""Cross-check reported numbers, provenance, and figures."""
import argparse
import hashlib
import json
from pathlib import Path

ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
summary=json.loads((root/'analysis/summary.json').read_text());rows=json.loads((root/'analysis/graded.json').read_text())
manifest=json.loads((root/'manifest.json').read_text());gate=json.loads((root/'gate.json').read_text())
checks={}
checks['complete_audited_comparison']=summary['complete'] and summary['validation_passed']
checks['complete_fixed_coverage']=len(rows)==96 and len({r['key'] for r in rows})==96 and len(list((root/'requests').glob('*.json')))==98
checks['all_24_initial_choices_match']=all(next(r for r in rows if (r['block'],r['policy'],r['index'])==(b,'admission',i))['initial_budget']==next(r for r in rows if (r['block'],r['policy'],r['index'])==(b,'live',i))['initial_budget'] for b in [0,1] for i in range(12))
checks['no_parser_issues']=not any(r['grading']['issue'] for r in rows)
checks['caps_never_credited']=all(not r['completed_correct'] and not r['correct_on_time'] for r in rows if r['finish'] in ('thinking_cap','answer_cap'))
checks['same_candidate_as_gate']=all(manifest['sources'][name]==sha for name,sha in gate['candidate_sources'].items())
checks['archived_sources_match']=all(hashlib.sha256((root/'sources'/name).read_bytes()).hexdigest()==sha for name,sha in manifest['sources'].items())
figure=json.loads((root/'analysis/figure-manifest.json').read_text())
checks['figure_matches_final_summary']=figure['summary_sha256']==hashlib.sha256((root/'analysis/summary.json').read_bytes()).hexdigest()
labels={'full':'Full thinking','arrival':'Arrival-only','admission':'Admission-only','live':'Live updates'}
report=(root.parents[1]/'REPORT.md').read_text()
checks['report_table_matches_final_numbers']=all(f"| {labels[r['policy']]} | {'**' if r['policy']=='live' else ''}{r['correct_on_time']}{'**' if r['policy']=='live' else ''} |" in report for r in summary['aggregate'])
checks['storage_roundtrip_verified']=json.loads((root/'analysis/storage-roundtrip.json').read_text())['passed']
result=dict(passed=all(checks.values()),checks=checks,source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(root/'analysis/final-record-check.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2));assert result['passed']
