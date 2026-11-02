#!/bin/bash
# After both session-2 conditions finish: score, audit, and dump every number the
# report needs into logs/session2-numbers.txt. CPU only; safe to run repeatedly.
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONE_WAITER="$(dirname "$CODE")"
REPO="$(cd "$ONE_WAITER/../../.." && pwd)"
ENV_ROOT="${LARB_W5_ENV_ROOT:-$REPO/.w5-env}"
PY="${LARB_W5_ANALYSIS_PYTHON:-$ENV_ROOT/analysis-venv/bin/python}"
cd "$ONE_WAITER" || exit 1
OUT=logs/session2-numbers.txt
: > "$OUT"
echo "== runs" >> "$OUT"
for d in results/job-6665417-one_at_a_time results/job-6665417-slack_rush_recovery; do
  [ -f "$d/run-complete.json" ] || { echo "$d: no run-complete.json yet" >> "$OUT"; continue; }
  "$PY" -B "$CODE/analyze5.py" --root "$d" > /dev/null 2>&1
  python3 - "$d" >> "$OUT" <<'EOF'
import json, sys
from pathlib import Path
root = Path(sys.argv[1])
c = json.loads((root / 'run-complete.json').read_text())
s = json.loads((root / 'analysis' / 'summary.json').read_text())
print(f"-- {root.name}: complete={c['complete']} answered={c['measured_requests']} "
      f"skipped={[x['block'] for x in c['skipped']]} measured_s={round(c['measured_phase_seconds'])}")
print(f"   deadline={s['relative_deadline_seconds']:.1f} unit={s['unit_seconds']:.1f} "
      f"horizon={[round(p['finished']-p['epoch']) for p in c['phases'][1:]]}")
for row in s['summary']:
    if row['n']:
        print(f"   {row['policy']:>10} n={row['n']} ontime={row['correct_on_time']} "
              f"eventual={row['completed_correct']} median={row['median_client_seconds']:.1f} "
              f"p95={row['p95_client_seconds']:.1f} "
              f"queue={row['mean_queue_seconds']:.1f} think={row['thinking_tokens']} "
              f"out={row['output_tokens']} cuts={row['live_reductions']} "
              f"binding={row['binding_live_cutoffs']} failures={row['failures']}")
print('   cut->finish s:', [round(x, 1) for x in s['binding_cut_to_finish_seconds']])
print('   tokens past short when cut:', s['reduction_after_short_tokens'])
print('   paired:', [(p['block'], p['index'],
                      '/'.join(str(int(p['on_time'][k])) for k in
                               ['fixed2048', 'fixed4096', 'live', 'live_one'])) for p in s['paired']])
print('   eventual:', [(p['block'], p['index'],
                       '/'.join(str(int(p['eventual'][k])) for k in
                                ['fixed2048', 'fixed4096', 'live', 'live_one'])) for p in s['paired']])
print('   think:', [(p['block'], p['index'],
                    '/'.join(str(p['thinking'][k]) for k in
                             ['fixed2048', 'fixed4096', 'live', 'live_one'])) for p in s['paired']])
EOF
done
echo "== verdicts" >> "$OUT"
python3 "$CODE/verdicts.py" >> "$OUT" 2>&1
echo "== coverage" >> "$OUT"
python3 "$CODE/coverage_audit.py" >> "$OUT" 2>&1
echo "== gpu log" >> "$OUT"
grep -E '^=== ' logs/session2b.log >> "$OUT" 2>/dev/null
echo "== done $(date -Is)" >> "$OUT"
