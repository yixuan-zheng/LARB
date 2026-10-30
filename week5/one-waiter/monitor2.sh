#!/bin/bash
# Append one line per minute: clock, phase progress, GPU use, cut count. CPU only.
HERE=/home/hice1/jwang3221/scratch/LARB/week5/one-waiter
OUT="$HERE/monitor2.log"
while true; do
  line="$(date +%H:%M:%S)"
  for d in "$HERE"/results/job-*; do
    [ -f "$d/progress.json" ] || continue
    prog=$(python3 -c "import json,sys;d=json.load(open('$d/progress.json'));print(','.join(f\"{p['phase']}:{len(p['client'])}{'*' if p['completed'] else ''}\" for p in d))" 2>/dev/null)
    cuts=$(grep -c live_reduction "$d/worker.jsonl" 2>/dev/null || echo 0)
    line="$line | $(basename "$d" | cut -d- -f3-): $prog cuts=$cuts"
  done
  line="$line | gpu=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits | head -1)MiB"
  echo "$line" >> "$OUT"
  grep -q 'chain done' "$HERE/session2b.log" && break
  sleep 60
done
