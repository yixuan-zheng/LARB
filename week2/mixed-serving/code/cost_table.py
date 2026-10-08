"""Measured-cost replay: run the *same* schedule on CPU with measured forward costs.

Role of this module
-------------------
This is the harness's cross-check, never its primary evidence.  It reuses
``serving_core`` (admission, budgets, batching, timestamps, SLO bookkeeping) and
replaces only the two forwards with lookups into a table measured by
``calibrate.py`` on the real GPU.  That buys three things:

* the scheduler can be validated end to end on a login node, in seconds;
* ``validate_harness.py`` can compare measured and replayed runs on the same trace
  (the ``measured_vs_replay`` gate);
* load/parameter sensitivity can be explored cheaply before spending GPU hours.

Every lookup reports how it was obtained -- ``measured`` (an exact cell),
``interpolated`` (nearest measured cell) or ``extrapolated`` -- and the run manifest
counts them, so a replay whose numbers came mostly from non-exact cells is visible
as such instead of looking like a measurement.

Cost table schema (written by ``calibrate.py``)::

    {"schema_version": 1,
     "source": {..., "kind": "measured_loop"},
     "cells": {"prefill": [{"preset","batch","chunk","ms","n","ctx"}],
               "decode":  [{"preset","batch","ctx","ms","n"}],
               "switch":  {"apply_ms": ..., "boundary_ms": ...}},
     "kv_bytes_per_token": 40960,
     "vram_budget_bytes": ...}
"""
from __future__ import annotations

import json
from pathlib import Path

import serving_core as core
import slo as slo_mod

SCHEMA_VERSION = 1
#: Fallback KV footprint per token, measured in Week 1 (S7: 40,960 B/token).
DEFAULT_KV_BYTES_PER_TOKEN = 40960
#: L40S usable VRAM for the loop: 48 GiB minus a safety margin for the driver and
#: the (single, shared) switchable weight set.
DEFAULT_VRAM_BUDGET_BYTES = 34 * 1024 ** 3


class CostTable:
    """Lookup structure over measured per-forward costs."""

    def __init__(self, doc: dict):
        if int(doc.get("schema_version", 0)) != SCHEMA_VERSION:
            raise ValueError(f"unsupported cost-table schema {doc.get('schema_version')!r}")
        self.doc = doc
        self.source = dict(doc.get("source", {}))
        self.kv_bytes_per_token = int(doc.get("kv_bytes_per_token",
                                              DEFAULT_KV_BYTES_PER_TOKEN))
        self.vram_budget_bytes = int(doc.get("vram_budget_bytes",
                                             DEFAULT_VRAM_BUDGET_BYTES))
        cells = doc["cells"]
        self.prefill = self._index(cells.get("prefill", []), ("preset", "batch", "chunk"))
        self.decode = self._index(cells.get("decode", []), ("preset", "batch"))
        self.switch = dict(cells.get("switch", {}))
        self.lookup_kinds = {}

    @staticmethod
    def _index(rows, keys) -> dict:
        out = {}
        for row in rows:
            out.setdefault(tuple(row[k] for k in keys), []).append(row)
        return out

    @staticmethod
    def load(path) -> "CostTable":
        return CostTable(json.loads(Path(path).read_text()))

    def _note(self, kind: str) -> None:
        self.lookup_kinds[kind] = self.lookup_kinds.get(kind, 0) + 1

    # -- nearest-cell lookup with a declared fallback ----------------------- #
    def _nearest(self, table: dict, key: tuple):
        exact = table.get(key)
        if exact:
            self._note("measured")
            return exact[0], "measured"
        same_preset = [k for k in table if k[:-1] == key[:-1]] or list(table)
        if not same_preset:
            raise KeyError(f"no measured cell for {key}")
        best = min(same_preset, key=lambda k: abs(k[-1] - key[-1]))
        self._note("interpolated")
        return table[best][0], "interpolated"

    def prefill_cost(self, preset: str, batch: int, chunk: int) -> dict:
        cell, kind = self._nearest(self.prefill, (preset, int(batch), int(chunk)))
        return {"ms": float(cell["ms"]), "lookup": kind, "cell": cell}

    def decode_cost(self, preset: str, batch: int) -> dict:
        if batch <= 0:
            return {"ms": 0.0, "lookup": "empty", "cell": None}
        cell, kind = self._nearest(self.decode, (preset, int(batch)))
        return {"ms": float(cell["ms"]), "lookup": kind, "cell": cell}

    def switch_cost_ms(self) -> float:
        return float(self.switch.get("apply_ms", 0.0)) + \
            float(self.switch.get("boundary_ms", 0.0))

    def describe(self) -> dict:
        return {"source": self.source,
                "prefill_cells": sum(len(v) for v in self.prefill.values()),
                "decode_cells": sum(len(v) for v in self.decode.values()),
                "switch": self.switch, "kv_bytes_per_token": self.kv_bytes_per_token,
                "vram_budget_bytes": self.vram_budget_bytes,
                "lookup_kinds": dict(self.lookup_kinds)}


class ReplayExecutor(core.StateApplierMixin):
    """Execute plans by looking their cost up in a measured table."""

    mode = "replay"

    def __init__(self, cost_table: CostTable, loop_us: float = 0.0):
        self.table = cost_table
        self.scheduler = core.Scheduler(core.EngineConfig())
        self.states = {}
        self.loop_us = float(loop_us)
        self.kv_high_water = 0

    def bind(self, config: core.EngineConfig) -> None:
        self.scheduler = core.Scheduler(config)

    # -- admission (the same arithmetic the GPU executor checks, minus torch) -- #
    def _kv_bytes(self, running, extra=None) -> int:
        total = sum((r.prompt_tokens + r.output_tokens_target) for r in running)
        if extra is not None:
            total += extra.prompt_tokens + extra.output_tokens_target
        return total * self.table.kv_bytes_per_token

    def can_admit(self, running, head, config) -> bool:
        return self._kv_bytes(running, head) <= self.table.vram_budget_bytes

    def on_admit(self, req, config) -> None:
        self.states[req.request_id] = req

    def on_retire(self, req) -> None:
        self.kv_high_water = max(self.kv_high_water, self._kv_bytes([req]))

    # -- one iteration ------------------------------------------------------ #
    def execute(self, plan, state, config, clock) -> dict:
        t_start = clock.now()
        gpu_ms, host_ms, switches = 0.0, 0.0, 0
        prefill_widths = []
        for group in plan.prefill_groups:
            padded = max(a.padded_len for a in group)
            cost = self.table.prefill_cost(plan.prefill_width, len(group), padded)
            gpu_ms += cost["ms"]
            prefill_widths.append(plan.prefill_width)
            clock.advance_to(clock.now() + cost["ms"] / 1000.0)
            one = core.SchedulerPlan(prefill=group, prefill_groups=[group],
                                     prefill_width=plan.prefill_width)
            self.apply_prefill(one, t_start, clock.now())
        if plan.decode:
            cost = self.table.decode_cost(plan.decode_width, len(plan.decode))
            gpu_ms += cost["ms"]
            clock.advance_to(clock.now() + cost["ms"] / 1000.0)
            if plan.prefill_width is not None and plan.prefill_width != plan.decode_width:
                # The phase switch is the only switch an iteration may perform, and
                # its measured cost is charged here rather than hidden in the cells.
                switches += 1
                host_ms += self.table.switch_cost_ms()
                clock.advance_to(clock.now() + self.table.switch_cost_ms() / 1000.0)
            self.apply_decode(plan, clock.now())
        host_ms += self.loop_us / 1000.0
        unstarted, decode_backlog = core.backlog_counts(state, plan)
        log = core.make_iteration_log(
            iteration=state.iteration, t_start_s=t_start, t_end_s=clock.now(),
            gpu_ms=gpu_ms, host_ms=host_ms, plan=plan, prefill_groups=plan.prefill_groups,
            prefill_widths=prefill_widths, decode_width=plan.decode_width,
            switches=switches,
            switch_apply_ms=self.table.switch_cost_ms() if switches else 0.0,
            waiting=len(state.waiting), running=len(state.running),
            completed=len(state.completed), mode=self.mode,
            unstarted=unstarted, decode_backlog=decode_backlog,
            note=self._note_lookups())
        return {"switches": switches, "log": log}

    def _note_lookups(self) -> str:
        kinds = self.table.lookup_kinds
        total = sum(kinds.values()) or 1
        interp = kinds.get("interpolated", 0)
        return f"lookups={total} interpolated={interp} ({interp / total:.0%})"


def replay_run(trace, config, policy, contract, cost_table: CostTable,
               warmup_s: float = 10.0, loop_us: float = 0.0) -> tuple:
    """Convenience wrapper: one replayed run -> ``(RunState, report)``."""
    executor = ReplayExecutor(cost_table, loop_us=loop_us)
    executor.bind(config)
    clock = core.VirtualClock()
    state = core.run_loop(executor, trace, config, policy, contract, clock)
    report = slo_mod.summarize_run(state, contract, warmup_s=warmup_s, wall_s=state.wall_s)
    report["mode"] = "replay"
    report["cost_lookups"] = dict(cost_table.lookup_kinds)
    return state, report
