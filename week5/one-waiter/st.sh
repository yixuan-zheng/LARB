#!/bin/bash
# One compact status line: clock, per-phase counts of the live run, GPU use.
cd /home/hice1/jwang3221/scratch/LARB/week5/one-waiter
echo -n "$(date +%H:%M:%S) "
for d in results/job-66654*; do
  [ -f "$d/progress.json" ] || continue
  python3 -c "
import json
d=json.load(open('$d/progress.json'))
print('$d'.split('6665417-')[-1]+': '+','.join(f\"{p['phase']}:{len(p['client'])}{'*' if p['completed'] else ''}\" for p in d), end=' | ')" 2>/dev/null
done
echo "gpu=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)M"
