#!/bin/bash
# Console for one_at_a_time / slack_rush_recovery progress. Usage: console.sh MODE
cd /home/hice1/jwang3221/scratch/LARB/week5/one-waiter || exit 1
RUN=${RUN:-results/job-6665417-one_at_a_time}
case "${1:-cnt}" in
  cnt)
    python3 -c "
import json
d=json.load(open('$RUN/progress.json'))
print(' '.join(f\"{p['phase']}={len(p['client'])}{'*' if p['completed'] else ''}\" for p in d))" 2>/dev/null ;;
  dur)
    python3 -c "
import json
d=json.load(open('$RUN/progress.json'))
print(' '.join(f\"{p['phase']}:{(round(p['finished']-p['epoch']) if p['completed'] else '-' )}\" for p in d))" 2>/dev/null ;;
  tok)
    python3 -c "
import json,glob
n=t=0
for f in glob.glob('$RUN/requests/*.json'):
    d=json.load(open(f)); n+=1; t+=len(d['token_ids'])
print(f'{n} saved answers, {t} tokens, mean {round(t/max(n,1))}')" 2>/dev/null ;;
  ev)
    python3 -c "
import json,collections
c=collections.Counter(json.loads(l)['event'] for l in open('$RUN/worker.jsonl'))
print(dict(c))" 2>/dev/null ;;
  gpu)
    nvidia-smi --query-gpu=memory.used,utilization.gpu --format=csv,noheader ;;
  log)
    tail -c 160 session2b.log; tail -c 160 scoring.log 2>/dev/null ;;
  score)
    grep -c scored scoring.log 2>/dev/null; ls "$RUN"/analysis 2>/dev/null | tr '\n' ' ' ;;
  done)
    ls "$RUN"/run-complete.json "$RUN"/run-failed.json 2>/dev/null ;;
esac
date +%H:%M:%S
