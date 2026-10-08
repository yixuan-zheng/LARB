"""Summarize paired decode screening from its saved raw JSON."""
import argparse
import csv
import json
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__)
p.add_argument('input', type=Path)
p.add_argument('--additional', type=Path, help='Complete previously unfinished cells from another job')
a = p.parse_args()
d = json.loads(a.input.read_text())
if a.additional:
    extra = json.loads(a.additional.read_text())
    for key in ('model', 'revision'):
        assert d['manifest'][key] == extra['manifest'][key], key
    assert d['protocol'] == extra['protocol'], 'measurement protocol differs'
    cells = {(c['batch'], c['context']):c for c in d['cells']}
    for c in extra['cells']:
        key = (c['batch'], c['context'])
        assert key in cells and not cells[key]['completed'], 'would replace completed evidence'
        if c['completed']:
            cells[key] = c
    d['cells'] = list(cells.values())
    d['completed'] = all(c['completed'] for c in d['cells'])
rows = []
for cell in d['cells']:
    if not cell['completed']:
        rows.append(dict(batch=cell['batch'], context=cell['context'], status=cell.get('status', 'incomplete')))
        continue
    c = cell['comparisons']['wall_ms']
    rows.append(dict(batch=cell['batch'], context=cell['context'], status='complete',
                     large_wall_ms=cell['summary']['large']['wall_ms']['median'],
                     small_wall_ms=cell['summary']['small']['wall_ms']['median'],
                     paired_reduction_percent=100*(1-c['mean_ratio']),
                     reduction_ci_low_percent=100*(1-c['ratio_hi']),
                     reduction_ci_high_percent=100*(1-c['ratio_lo']),
                     speedup=c['speedup'], peak_allocated_gib=cell['peak_allocated_bytes']/1024**3,
                     screen_pass=c['ratio_hi'] <= 0.9))
fields = list(next(r for r in rows if r['status'] == 'complete'))
with a.input.with_name('summary.csv').open('w') as h:
    w = csv.DictWriter(h, fields); w.writeheader(); w.writerows(rows)
print(json.dumps(dict(completed=d['completed'], rows=rows), indent=2))
