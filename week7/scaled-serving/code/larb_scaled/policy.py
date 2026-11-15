"""Pure pressure and cut policy for the scaled rig.

No vLLM, no CUDA, no clocks. The controller supplies the waiting count and the
request states; this module decides whether pressure is present and which one
request, if any, is cut.
"""
import math
from dataclasses import dataclass
from typing import Iterable, List, Optional

SHORT = 4096
LONG = 8192
CUT_TARGET = 4096
PROGRESS_FLOOR = 512
MIN_SAVING = 1024
ARMS = ("fixed4k", "fixed6k", "fixed8k", "arrival", "live")


def pressure_threshold(max_num_seqs: int, fraction: float = 0.25, minimum: int = 4) -> int:
    if max_num_seqs < 1:
        raise ValueError("max_num_seqs must be positive")
    if not 0 < fraction <= 1:
        raise ValueError("fraction must be in (0, 1]")
    return max(minimum, int(math.ceil(fraction * max_num_seqs)))


def admission_budget(arm: str, waiting: int, threshold: int,
                     short: int = SHORT, long: int = LONG) -> int:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    if waiting < 0 or threshold < 1 or not 0 < short < long:
        raise ValueError("invalid admission settings")
    if arm == "fixed4k":
        return short
    if arm == "fixed6k":
        return 6096
    if arm == "fixed8k":
        return long
    return short if waiting >= threshold else long


@dataclass
class PressureTracker:
    threshold: int
    persistence_steps: int = 2
    consecutive: int = 0
    pressure: bool = False

    def update(self, waiting: int) -> bool:
        if waiting < 0:
            raise ValueError("waiting must be non-negative")
        if waiting >= self.threshold:
            self.consecutive += 1
        else:
            self.consecutive = 0
        self.pressure = self.consecutive >= self.persistence_steps
        return self.pressure

    def reset(self):
        self.consecutive = 0
        self.pressure = False


def remaining_budget(state) -> int:
    return max(0, state.budget - len(state.output))


def eligible(state, cut_to: int = CUT_TARGET, progress_floor: int = PROGRESS_FLOOR,
             min_saving: int = MIN_SAVING) -> bool:
    """A request is cuttable only while it is still thinking and worth cutting."""
    state.refresh()
    if state.close_index is not None or state.force_start is not None:
        return False
    progress = len(state.output)
    if state.budget <= cut_to:
        return False
    if progress < progress_floor:
        return False
    if state.budget - progress < min_saving:
        return False
    return True


def choose_victim(states: Iterable) -> Optional[object]:
    """Choose the eligible request with the largest remaining budget.

    Ties break on earliest arrival, then request key for determinism.
    """
    candidates = [state for state in states if eligible(state)]
    if not candidates:
        return None
    return max(candidates, key=lambda s: (remaining_budget(s),
                                          -(s.arrival_ts if s.arrival_ts is not None else 1e18),
                                          s.key))


def apply_cut(state, cut_to: int = CUT_TARGET, reason: str = "pressure") -> bool:
    if state.budget <= cut_to:
        return False
    return state.change(cut_to, state.version + 1, reason=reason)


def pressure_snapshot(waiting: int, max_num_seqs: int, fraction: float = 0.25,
                      minimum: int = 4) -> dict:
    threshold = pressure_threshold(max_num_seqs, fraction, minimum)
    return dict(waiting=waiting, threshold=threshold, max_num_seqs=max_num_seqs,
                ratio=waiting / max_num_seqs if max_num_seqs else None,
                strong=waiting >= threshold)


def validate_policy_config(config: dict):
    required = ("threshold_fraction", "threshold_minimum", "threshold_grid",
                "persistence_steps")
    pressure = config.get("pressure", {})
    for key in required:
        if key not in pressure:
            raise ValueError(f"missing pressure.{key}")
    cut = config.get("cut", {})
    for key in ("target", "progress_floor", "min_saving"):
        if key not in cut:
            raise ValueError(f"missing cut.{key}")
    if cut["target"] >= LONG:
        raise ValueError("cut target must be below the long budget")
    return True
