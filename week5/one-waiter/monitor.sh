#!/bin/bash
OUT=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter/results/job-6663679-constant_pressure
while true; do
  t=$(date +%H:%M:%S)
  p=$(python3 -c "import json;d=json.load(open('$OUT/progress.json'));print(' '.join(f\"{x['phase']}:{len(x['client'])}{'*' if x['completed'] else ''}\" for x in d))" 2>/dev/null)
  echo "$t $p" >> /home/hice1/jwang3221/scratch/LARB/week5/one-waiter/monitor.log
  grep -q 'finished=' /home/hice1/jwang3221/scratch/LARB/week5/one-waiter/pressure.log && break
  sleep 20
done
