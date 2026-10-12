"""Width policies for the mixed-serving harness.

A policy answers exactly two questions per iteration, because the mechanism
supports exactly one FFN width per batch::

    policy.prefill_width(view) -> preset name      # one width for all prefill forwards
    policy.decode_width(view)  -> preset name      # one width for the decode batch

``view`` is ``serving_core.EngineView``: it carries the arrivals that have
already happened, the prompt lengths, the number in flight, the iteration index
and the SLOs -- and deliberately *not* the trace's output lengths, so no policy
can peek at the future (enforced by a field check in ``EngineView``).

The three configurations the harness compares
---------------------------------------------
``static_large``  every forward at the full-width preset (the quality reference).
``static_small``  every forward at the narrow preset.
``phase_hybrid``  prefill narrow, decode wide: **exactly one switch per request**,
                  at its own prefill/decode boundary.  This is the S9 mechanism
                  measured in Week 1 (it captures 0.99-1.01x of the static prefill
                  win at <=0.64 ms boundary cost), and the width history it
                  produces is the ``SL_early`` schedule the frozen Week 1 quality
                  harness already scored on GSM8K dev (-1.6 pp, inside the floor).

``load_driven`` is a **placeholder owned by Week 2 workstream C**, not a result:
it exists so the policy interface is exercised by something other than the three
fixed configurations.  Any number produced with it is labelled ``stub``.

``chunked_prefill`` is not a width policy: it is an extensible scheduling lever
carried by ``EngineConfig.prefill_chunk`` (lower priority, sanity only).
"""
from __future__ import annotations

from dataclasses import dataclass

#: Preset names in the pinned presets.json.
PRESETS = ("large", "small", "medium")
#: The two presets this harness compares.  ``medium`` exists in the preset file
#: but Week 1 showed it is dominated (it never won a grid point), so it is out of
#: the primary matrix by design rather than by omission.
COMPARED = ("large", "small")


class WidthPolicy:
    """Base class: subclasses set ``name`` and implement the two choices."""

    name = "base"
    #: Recorded in the run manifest; True for anything that is not a real result.
    stub = False

    def prefill_width(self, view) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def decode_width(self, view) -> str:  # pragma: no cover - interface
        raise NotImplementedError

    def describe(self) -> dict:
        return {"name": self.name, "stub": bool(self.stub), "class": type(self).__name__}

    def on_iteration(self, plan, result) -> None:
        """Hook called after each iteration; default does nothing."""


@dataclass
class StaticPolicy(WidthPolicy):
    """One width everywhere (``static_large`` / ``static_small``)."""

    preset: str = "large"
    name = "static"

    def __post_init__(self) -> None:
        if self.preset not in PRESETS:
            raise ValueError(f"unknown preset {self.preset!r}")
        self.name = f"static_{self.preset}"

    def prefill_width(self, view) -> str:
        return self.preset

    def decode_width(self, view) -> str:
        return self.preset


@dataclass
class PhaseHybridPolicy(WidthPolicy):
    """Narrow prefill, wide decode: the single-switch phase policy."""

    prefill: str = "small"
    decode: str = "large"
    name = "phase_hybrid"
    stub = False

    def prefill_width(self, view) -> str:
        return self.prefill

    def decode_width(self, view) -> str:
        return self.decode

    def describe(self) -> dict:
        out = super().describe()
        out.update({"prefill": self.prefill, "decode": self.decode,
                    "max_switches_per_request": 1,
                    "width_history_equivalent": "week1/quality schedules.SL_early"})
        return out


@dataclass
class LoadDrivenPolicy(WidthPolicy):
    """PLACEHOLDER (Week 2 workstream C): TTFT-protected, Large-first switching.

    Shape follows the Week 1 evidence: keep decode wide, use the narrow preset
    only for prefill under queue pressure, with a minimum dwell so the policy
    cannot flap.  It honours the allowed-transition list produced by
    ``week1/quality`` (both directions allowed, dwell >= 4 steps) instead of
    inventing a per-step quality penalty.  The very first decision and the first
    change after startup are free (there is no dwell to owe yet); every change
    after that must wait ``min_dwell_steps`` iterations.

    This is *not* an evaluated policy: the harness only needs something to prove
    the interface admits an online, load-aware decision.  Results computed with it
    carry ``policy_stub: true``.
    """

    narrow: str = "small"
    wide: str = "large"
    #: Queue depth at or above which prefill goes narrow.
    pressure_threshold: int = 8
    #: Minimum decode steps between two width changes (Week 1 floor is 4).
    min_dwell_steps: int = 4
    name = "load_driven"
    stub = True

    def __post_init__(self) -> None:
        if self.min_dwell_steps < 4:
            raise ValueError("week1/quality allows no dwell below 4 steps")
        self._last_prefill = None
        self._steps_since_switch = self.min_dwell_steps

    def prefill_width(self, view) -> str:
        want = self.narrow if view.queue_depth >= self.pressure_threshold else self.wide
        if self._last_prefill is None:
            self._last_prefill = want
            return want
        if want != self._last_prefill:
            if self._steps_since_switch < self.min_dwell_steps:
                return self._last_prefill
            self._steps_since_switch = 0
            self._last_prefill = want
        return self._last_prefill

    def decode_width(self, view) -> str:
        # Large-first: decode always prefers the wide preset (Week 1: decode width
        # is unresolvable in latency, and the quality evidence only certifies
        # Large-first schedules).
        return self.wide

    def on_iteration(self, plan, result) -> None:
        self._steps_since_switch += 1


POLICIES = {
    "static_large": lambda: StaticPolicy("large"),
    "static_small": lambda: StaticPolicy("small"),
    "phase_hybrid": lambda: PhaseHybridPolicy(),
    "load_driven": lambda: LoadDrivenPolicy(),
}


def build_policy(name: str) -> WidthPolicy:
    if name not in POLICIES:
        raise ValueError(f"unknown policy {name!r}; have {sorted(POLICIES)}")
    return POLICIES[name]()


def policy_names() -> list:
    return list(POLICIES)
