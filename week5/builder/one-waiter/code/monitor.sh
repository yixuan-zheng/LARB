#!/bin/bash
CODE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ONE_WAITER="$(dirname "$CODE")"
OUT="$ONE_WAITER/results/job-6663679-constant_pressure"
while true; do
  t=$(date +%H:%M:%S)
  p=$(python3 -c "import json;d=json.load(open('$OUT/progress.json'));print(' '.join(f\"{x['phase']}:{len(x['client'])}{'*' if x['completed'] else ''}\" for x in d))" 2>/dev/null)
  echo "$t $p" >> "$ONE_WAITER/logs/monitor.log"
  grep -q 'finished=' "$ONE_WAITER/logs/pressure.log" && break
  sleep 20
done
