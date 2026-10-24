"""CPU reference for an explicitly adapted LASER policy, not a serving engine.

Sources, choices, and unverified integration gates are in contract.json/REPORT.md.
No labels, answer keys, model imports, or validation examples are used here.
"""
from dataclasses import dataclass, field
import math


@dataclass(frozen=True)
class Parameters:
    target: float = 10.0
    base: float = .95
    beta: float = .04
    gamma: float = 1.0
    alpha: float = .3
    lower: float = .88
    upper: float = .97
    base_chunks: int = 10
    min_chunks: int = 2

    def __post_init__(self):
        numbers = (self.target, self.base, self.beta, self.gamma, self.alpha, self.lower, self.upper)
        if not all(math.isfinite(v) for v in numbers):
            raise ValueError('Nonfinite policy parameter')
        if not (self.target > 0 and 0 < self.alpha <= 1 and self.beta >= 0 and self.gamma >= 0
                and 0 <= self.lower <= self.base <= self.upper <= 1
                and self.min_chunks >= 2 and self.base_chunks >= self.min_chunks):
            raise ValueError('Invalid policy parameter')


def budget(prompt_tokens, active, params=Parameters()):
    """Paper Eqs. 6–8: ATP chunks, not tokens. Count admission snapshot once."""
    if prompt_tokens < 0 or active < 0:
        raise ValueError('Negative length/load')
    difficulty = min(1.5, max(.6, .6 + (prompt_tokens - 50) / 225 * .9))
    return max(params.min_chunks, math.floor(params.base_chunks * difficulty *
                                           min(1., params.target / max(1, active))))


@dataclass
class Load:
    params: Parameters = field(default_factory=Parameters)
    ema: float = 0.

    def observe_atp(self, active):
        if not math.isfinite(active) or active < 0:
            raise ValueError('Invalid active-request count')
        p = self.params
        self.ema = p.alpha * active + (1 - p.alpha) * self.ema
        return min(p.upper, max(p.lower, p.base - p.beta * math.tanh(
            p.gamma * (self.ema - p.target) / p.target)))


def confidence(top_logprobs, *, complete, nonempty_answer):
    """Geometric mean of raw top-1 probabilities, all generated probe tokens.

    Each position is a sequence of (rank, raw logprob) candidates. Require rank
    one; dictionary insertion order or sampled-token probability is not top-1.
    Explicit adaptation: include braces/format tokens; exclude only terminal
    EOS/think-close BEFORE calling. The probe prompt is never a scored token.
    Missing, capped, unparsable, or invalid results cannot request early exit.
    """
    if not complete or not nonempty_answer or not top_logprobs:
        return None
    values = []
    for candidates in top_logprobs:
        tops = [value for rank, value in candidates if rank == 1]
        if len(tops) != 1 or not math.isfinite(tops[0]) or tops[0] > 0:
            return None
        values.append(tops[0])
    return math.exp(math.fsum(values) / len(values))


@dataclass
class Request:
    phase: str
    key: str
    chunks: int
    token_cap: int = 16384
    state: str = 'thinking'
    count: int = 0
    prefix: tuple = ()
    pending: str | None = None
    issued: int = 0

    def __post_init__(self):
        if self.chunks < 2 or self.token_cap < 1 or not self.phase or not self.key:
            raise ValueError('Invalid request identity/budget')

    def checkpoint(self, prefix, *, atp=False, natural_close=False):
        if self.state != 'thinking':
            raise RuntimeError('Cannot update reasoning outside thinking phase')
        prefix = tuple(prefix)
        if prefix[:len(self.prefix)] != self.prefix:
            raise ValueError('Continuation changed committed prefix')
        if len(prefix) > self.token_cap:
            raise ValueError('Backend crossed reasoning token safety cap')
        progressed = len(prefix) > len(self.prefix)
        self.prefix = prefix
        if natural_close:
            self.state = 'answer'
            return None
        if atp and progressed:
            self.count += 1
        if len(prefix) == self.token_cap:
            self.state = 'closing'
            return None
        if atp and progressed:
            self.issued += 1
            self.pending = f'{self.phase}/{self.key}/probe/{self.issued}'
            self.state = 'probing'
            return self.pending
        return None

    def accept_probe(self, probe_id, prefix, score, threshold):
        if self.state != 'probing' or probe_id != self.pending or tuple(prefix) != self.prefix:
            raise ValueError('Stale, foreign, or mismatched probe')
        if not math.isfinite(threshold) or not 0 <= threshold <= 1:
            raise ValueError('Invalid threshold')
        if score is not None and (not math.isfinite(score) or not 0 <= score <= 1):
            raise ValueError('Invalid confidence')
        self.pending = None
        self.state = ('closing' if (score is not None and score > threshold)
                      or self.count >= self.chunks else 'thinking')
        return self.state

    def close_completed(self):
        if self.state != 'closing':
            raise RuntimeError('No transition pending')
        self.state = 'answer'

    def finish(self, *, eos, within_answer_cap):
        if self.state != 'answer':
            raise RuntimeError('A probe or partial cue is not a final answer')
        self.state = 'complete' if eos and within_answer_cap else 'failed'

    def cancel(self):
        self.pending = None
        self.state = 'cancelled'


@dataclass
class Costs:
    calls: dict = field(default_factory=dict)

    def record(self, call_id, *, kind, prompt_tokens, computed_prefill_tokens,
               cached_tokens, decoded_tokens, discarded_tokens, start, end):
        """Submitted prefix and executed/cached prefix are separate quantities.

        Scheduler-derived computed counts may differ from submitted minus cache
        (block recomputation). Wall latency uses client clocks, not summed calls.
        """
        counts = (prompt_tokens, computed_prefill_tokens, cached_tokens,
                  decoded_tokens, discarded_tokens)
        if (call_id in self.calls or kind not in ('reason', 'probe', 'final')
                or any(type(n) is not int or n < 0 for n in counts)
                or cached_tokens > prompt_tokens or discarded_tokens > decoded_tokens
                or not math.isfinite(start) or not math.isfinite(end) or end < start):
            raise ValueError('Incomplete, duplicated, or invalid cost record')
        self.calls[call_id] = dict(kind=kind, prompt_tokens=prompt_tokens,
            computed_prefill_tokens=computed_prefill_tokens, cached_tokens=cached_tokens,
            decoded_tokens=decoded_tokens, discarded_tokens=discarded_tokens,
            start=start, end=end)

    def totals(self):
        names = ('prompt_tokens', 'computed_prefill_tokens', 'cached_tokens',
                 'decoded_tokens', 'discarded_tokens')
        return dict(calls=len(self.calls), **{n:sum(c[n] for c in self.calls.values()) for n in names})
