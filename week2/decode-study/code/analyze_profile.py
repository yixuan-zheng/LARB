"""Aggregate diagnostic profiler activity; never treat profiled span as production latency."""
import argparse,csv,json,statistics
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('input',type=Path);a=p.parse_args()
d=json.loads(a.input.read_text());rows=[]
for cell in d['cells']:
    for width in ['large','small']:
        ps=[x for x in cell['profiles'] if x['width']==width]
        if not ps:continue
        row={'batch':cell['batch'],'context':cell['context'],'width':width,'traces':len(ps)}
        for metric in ['gpu_activity_sum_ms','gpu_activity_union_ms','gpu_activity_span_ms','gpu_gap_ms','gpu_event_count']:
            row[metric]=statistics.median(x[metric] for x in ps)
        for bucket in ['FFN','ATTENTION']:
            row[bucket.lower()+'_device_ms']=statistics.median(x['buckets'][bucket]['device_ms'] for x in ps)
            row[bucket.lower()+'_cpu_ms']=statistics.median(x['buckets'][bucket]['cpu_ms'] for x in ps)
        row['other_device_ms']=statistics.median(x['gpu_activity_sum_ms']-x['buckets']['FFN']['device_ms']-x['buckets']['ATTENTION']['device_ms'] for x in ps)
        for metric in ['wall_ms','gpu_ms']:
            values=cell.get('unprofiled_samples',{}).get(width,[])
            row['annotated_unprofiled_'+metric]=statistics.median(x[metric] for x in values) if values else None
        # Fractions are ratios of per-trace values, then medians; scopes are disjoint.
        for bucket in ['FFN','ATTENTION']:
            row[bucket.lower()+'_activity_percent']=statistics.median(100*x['buckets'][bucket]['device_ms']/x['gpu_activity_sum_ms'] for x in ps)
        row['gap_span_percent']=statistics.median(100*x['gpu_gap_ms']/x['gpu_activity_span_ms'] for x in ps)
        rows.append(row)
with a.input.with_name('summary.csv').open('w') as h:
    w=csv.DictWriter(h,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
print(json.dumps({'completed':d['completed'],'rows':rows},indent=2))
