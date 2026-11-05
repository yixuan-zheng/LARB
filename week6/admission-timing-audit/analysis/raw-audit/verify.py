"""Verify reconstructed counts, paired identities and immutable input hashes; no inference."""
import argparse,hashlib,json
from pathlib import Path
from collections import defaultdict
from extract import SOURCES
p=argparse.ArgumentParser();p.add_argument('--derived',type=Path,default=Path(__file__).resolve().parent/'derived');a=p.parse_args();D=a.derived
for run,root in SOURCES:
 info=json.loads((D/run/'extraction-summary.json').read_text());rows=json.loads((D/run/'requests.json').read_text());original=json.loads((root/'summary.json').read_text());expected={r['key']:r for r in original['rows']};assert len(rows)==len(expected)==info['request_count']
 for name,digest in info['input_hashes'].items():assert hashlib.sha256((root/name).read_bytes()).hexdigest()==digest,(run,name)
 for r in rows:
  assert all(r[k]==v for k,v in expected[r['key']].items())
  assert r['received']>=r['scheduled'] and r['first_active']>=r['received']
  assert r['thinking_tokens']+r['answer_tokens_after_close']<=r['output_tokens']
  assert r['good']==bool(r['correct'] and r['timely'])
  assert abs(r['queue_seconds']+r['service_seconds']-(r['finish']-r['received']))<1e-8
  # Clock samples from independent processes may straddle the same EOS event.
  assert abs(r['scheduler_release_lag_seconds'])<1
 for ph in json.loads((D/run/'phases.json').read_text()):
  old=next(x for x in original['summary'] if x['phase']==ph['phase']);assert ph['correct']==old['correct'] and ph['good']==old['correct_on_time'] and ph['output_tokens']==old['total_output_tokens']
 # Verify proposed online features do not access a request before its arrival.
 index={r['key']:r for r in rows}
 for frame in json.loads((D/run/'frames.json').read_text()):
  for key in frame['waiting']:
   assert index[key]['received']<=frame['now'] and index[key]['scheduled']<=frame['now']
  for state in frame['active']:
   assert state['closed'] or state['close_index'] is None
   assert state['cued'] or state['cue_start'] is None
  assert frame['tau_online'] is None or frame['tau_online']>0
summary=json.loads((D/'audit-summary.json').read_text());assert summary['coverage']==dict(all_records=244,measured_records=232,probe_records=12,runs=3,paired_current_rows=40)
pairs=json.loads((D/'paired-outcomes.json').read_text());assert len({(r['run'],r['condition'],r['id']) for r in pairs})==40;assert sum(r['net_good'] for r in pairs)==0;assert sum(r['net_correct'] for r in pairs)==-3
assert summary['reuse']['same_step_reuse']==summary['reuse']['queued_release_observations']==105
paths=json.loads((D/'paired-token-paths.json').read_text());assert sum(r['prefix_diverges_before_cut'] for r in paths)==10 and sum(r['cut'] is not None for r in paths)==16
print(json.dumps(dict(audit='PASS',raw_records=244,measured_records=232,immutable_input_files_verified=21,paired_cases=40,queued_releases=105,counterfactual_accuracy_computed=False,gpu_submissions=0),indent=2))
