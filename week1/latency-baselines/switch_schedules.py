"""Pure-stdlib width plans and switching schedules for the dynamic FFN-width extension.

Why this module exists
----------------------
The static suite (s0-s7) froze one FFN width per process. The dynamic extension makes
the width a *per-iteration* runtime choice, which means the set of widths to visit and
the order to visit them in become first-class experimental variables. Keeping that
algebra stdlib-only (no torch) means a login node can validate it in seconds, mirroring
the ``latency_math`` / ``test_flop_model`` split already used here.

``dynamic_lib`` imports this to drive the torch/CUDA side; ``test_switch_schedules.py``
imports only this plus ``latency_math``.

What a plan is
--------------
A ``WidthPlan`` is a frozen per-layer FFN width vector (35 ints for E4B) plus a name.
The published presets are plans; ``uniform``/``per_layer`` build arbitrary ones. A
*schedule* is an ordered list of plans, one per forward pass, which is exactly what
iteration-level switching consumes.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path

NUM_LAYERS = 35
PRESETS = ("small", "medium", "large")
#: Full (unsliced) E4B FFN width. Switching up to this needs the full weights resident.
WIDTH_FULL = 16384
PRESETS_PATH = Path(__file__).resolve().parent.parent.parent / "preflight" / "code" / "presets.json"
#: Fallback used only if ``presets.json`` cannot be read; kept in sync with the pinned
#: Google slicing configs (small: 20 narrow layers, medium: 10, large: 0).
_FALLBACK_WIDTHS = {
    "small": (8192,) * 10 + (16384,) * 15 + (8192,) * 10,
    "medium": (8192,) * 5 + (16384,) * 25 + (8192,) * 5,
    "large": (16384,) * NUM_LAYERS,
}


def load_preset_widths() -> dict:
    """``{preset: (width per layer)}`` from the pinned presets.json, with a fallback."""
    try:
        data = json.loads(PRESETS_PATH.read_text())["presets"]
        widths = {name: tuple(int(w) for w in spec["ffn_hidden_dims"])
                  for name, spec in data.items()}
        if all(len(w) == NUM_LAYERS for w in widths.values()):
            return widths
    except Exception:  # noqa: BLE001 - a missing file must not make schedules unusable
        pass
    return {name: tuple(w) for name, w in _FALLBACK_WIDTHS.items()}


@dataclass(frozen=True)
class WidthPlan:
    """A named per-layer FFN width vector. Immutable; safe to share across configs."""

    name: str
    widths: tuple

    def __post_init__(self) -> None:
        widths = tuple(int(w) for w in self.widths)
        object.__setattr__(self, "widths", widths)
        if len(widths) != NUM_LAYERS:
            raise ValueError(f"plan {self.name!r} has {len(widths)} widths, "
                             f"expected {NUM_LAYERS}")
        if any(w <= 0 for w in widths):
            raise ValueError(f"plan {self.name!r} has a non-positive width")

    # -- constructors ------------------------------------------------------- #
    @staticmethod
    def from_preset(preset: str, widths_map: dict | None = None) -> "WidthPlan":
        widths_map = widths_map or load_preset_widths()
        if preset not in widths_map:
            raise ValueError(f"unknown preset {preset!r} (have {sorted(widths_map)})")
        return WidthPlan(preset, widths_map[preset])

    @staticmethod
    def uniform(width: int, name: str | None = None) -> "WidthPlan":
        return WidthPlan(name or f"uniform{int(width)}", (int(width),) * NUM_LAYERS)

    @staticmethod
    def per_layer(name: str, widths) -> "WidthPlan":
        return WidthPlan(name, tuple(widths))

    # -- introspection ------------------------------------------------------ #
    @property
    def max_width(self) -> int:
        return max(self.widths)

    @property
    def narrow_layers(self) -> int:
        return sum(1 for w in self.widths if w < self.max_width)

    @property
    def summed_width(self) -> int:
        return int(sum(self.widths))

    def describe(self) -> dict:
        """JSON-safe summary for a measurement record (never the full vector)."""
        return {"name": self.name, "narrow_layers": self.narrow_layers,
                "summed_width": self.summed_width, "distinct_widths": sorted(set(self.widths))}



# --------------------------------------------------------------------------- #
# Schedule generators: an ordered list of plans, one per forward pass
# --------------------------------------------------------------------------- #
def schedule_constant(preset: str, iterations: int, widths_map: dict | None = None) -> list:
    plan = WidthPlan.from_preset(preset, widths_map)
    return [plan] * int(iterations)


def schedule_alternate(a: str, b: str, iterations: int, widths_map: dict | None = None) -> list:
    pa, pb = WidthPlan.from_preset(a, widths_map), WidthPlan.from_preset(b, widths_map)
    return [pa if i % 2 == 0 else pb for i in range(int(iterations))]


def schedule_block(a: str, b: str, block: int, iterations: int,
                   widths_map: dict | None = None) -> list:
    if block < 1:
        raise ValueError("block must be >= 1")
    pa, pb = WidthPlan.from_preset(a, widths_map), WidthPlan.from_preset(b, widths_map)
    return [pa if (i // int(block)) % 2 == 0 else pb for i in range(int(iterations))]


def schedule_random(a: str, b: str, iterations: int, seed: int = 6222,
                    widths_map: dict | None = None) -> list:
    pa, pb = WidthPlan.from_preset(a, widths_map), WidthPlan.from_preset(b, widths_map)
    rng = random.Random(int(seed))
    return [pa if rng.random() < 0.5 else pb for _ in range(int(iterations))]


def schedule_phase(prefill: str, decode: str, iterations: int, prefill_units: int = 1,
                   widths_map: dict | None = None) -> list:
    """First ``prefill_units`` forwards at ``prefill`` width, the rest at ``decode`` width.

    Index 0 is the prefill; a single switch therefore sits at the prefill/decode boundary.
    """
    widths_map = widths_map or load_preset_widths()
    pp, dp = WidthPlan.from_preset(prefill, widths_map), WidthPlan.from_preset(decode, widths_map)
    units = max(1, int(prefill_units))
    return [pp if i < units else dp for i in range(int(iterations))]


def resolve_schedule(spec: str, iterations: int, seed: int = 6222,
                     widths_map: dict | None = None) -> tuple:
    """Parse a schedule spec into ``(name, [WidthPlan, ...])``.

    ``const:large`` | ``alternate:large:small`` | ``block:large:small:4`` |
    ``random:large:small`` | ``phase:small:large`` | ``uniform:8192``
    """
    parts = spec.split(":")
    kind = parts[0]
    widths_map = widths_map or load_preset_widths()
    if kind == "const":
        return f"const_{parts[1]}", schedule_constant(parts[1], iterations, widths_map)
    if kind == "alternate":
        return f"alt_{parts[1]}_{parts[2]}", schedule_alternate(parts[1], parts[2], iterations, widths_map)
    if kind == "block":
        block = int(parts[3])
        return f"block{block}_{parts[1]}_{parts[2]}", schedule_block(parts[1], parts[2], block,
                                                                     iterations, widths_map)
    if kind == "random":
        return f"rand_{parts[1]}_{parts[2]}", schedule_random(parts[1], parts[2], iterations,
                                                              seed, widths_map)
    if kind == "phase":
        return f"phase_{parts[1]}_{parts[2]}", schedule_phase(parts[1], parts[2], iterations,
                                                              1, widths_map)
    if kind == "uniform":
        plan = WidthPlan.uniform(int(parts[1]))
        return plan.name, [plan] * int(iterations)
    raise ValueError(f"unknown schedule spec {spec!r}")


def width_weighted_ms(per_preset_ms: dict, plans: list) -> float:
    """Mean of per-plan medians, i.e. the static prediction for a switching schedule.

    The measured schedule mean is compared against this to isolate the cost of
    *alternation itself* from the cost of the widths involved.
    """
    if not plans:
        raise ValueError("empty schedule")
    total = 0.0
    for plan in plans:
        if plan.name not in per_preset_ms:
            raise KeyError(f"no measured median for plan {plan.name!r}")
        total += float(per_preset_ms[plan.name])
    return total / len(plans)
