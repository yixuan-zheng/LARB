"""Small CPU scoring boundary: unfinished/capped answers cannot be successes."""
from collections import Counter
import math
import statistics


def finish_kind(raw, cap=None):
    if cap:
        return cap
    if raw is None:
        return 'missing_final'
    ids=raw['token_ids']
    if (raw['finished'] and raw['finish_reason']=='stop' and ids and
            raw['close_id'] in ids and ids[-1]==raw['eos_id']):
        return 'normal'
    return 'missing_thinking_close' if raw['close_id'] not in ids else str(raw['finish_reason'])


def outcome(correct, finish, elapsed, deadline):
    if elapsed is not None and elapsed<0:
        raise ValueError('Client receipt precedes scheduled arrival')
    eventual=bool(correct and finish=='normal')
    return dict(completed_correct=eventual,
                correct_on_time=eventual and elapsed is not None and elapsed<=deadline)


def summarize(rows,horizon):
    completed=[r['client_completion_seconds'] for r in rows if r['client_completion_seconds'] is not None]
    queue=[r['queue_seconds'] for r in rows if r.get('queue_seconds') is not None]
    return dict(n=len(rows),correct_on_time=sum(r['correct_on_time'] for r in rows),
                completed_correct=sum(r['completed_correct'] for r in rows),
                correct_on_time_per_minute=60*sum(r['correct_on_time'] for r in rows)/horizon,
                observation_horizon_seconds=horizon,
                median_client_seconds=statistics.median(completed) if completed else None,
                p95_client_seconds=sorted(completed)[math.ceil(.95*len(completed))-1] if completed else None,
                mean_queue_seconds=statistics.mean(queue) if queue else None,
                median_queue_seconds=statistics.median(queue) if queue else None,
                terminal_receipts=len(completed),normal_completions=sum(r['finish']=='normal' for r in rows),
                failures=dict(Counter(r['finish'] for r in rows if r['finish']!='normal')),
                live_reductions=sum(r['live_reduction'] for r in rows),
                binding_live_cutoffs=sum(r['binding_live_cutoff'] for r in rows),
                thinking_tokens=sum(r['thinking_tokens'] or 0 for r in rows),
                cue_tokens=sum(r.get('cue_tokens',0) for r in rows),
                output_tokens=sum(r.get('output_tokens') or 0 for r in rows),
                token_accounting_complete=all(r.get('output_tokens') is not None for r in rows),
                answer_tokens=sum(r['answer_tokens'] or 0 for r in rows))
