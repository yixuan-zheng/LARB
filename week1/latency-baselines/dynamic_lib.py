"""Dynamic iteration-level FFN width switching: mechanism, schedules, instrumentation.

Scope
-----
This is the torch/CUDA half of the Week 1 dynamic-switching extension. The static suite
(s0-s7) deliberately froze one FFN width per process; this module makes the width a
*per-iteration* runtime choice on a single, full-weight Gemma 3n text model and measures
what that costs and what it buys. It reuses every instrument from ``latency_lib``
(timer, interleaved harness, L2 flusher, clock guard, VRAM budget, records) and the
stdlib schedule algebra in ``switch_schedules``.

Design, and why it differs from the preflight pilot
---------------------------------------------------
``preflight/code/pace_bounded_research.py`` monkey-patched a ``width_forward`` that
sliced ``gate_proj.weight[:w]``, ``up_proj.weight[:w]`` and ``down_proj.weight[:, :w]``
on every call with the full weights resident. That is a sound starting point and is kept
here as ``slice_mode="view"`` for parity, but it has two measurement problems this module
exists to remove:

* ``down_proj[:, :w]`` is a **non-contiguous** column slice. The static workers
  (``build_worker.py``) explicitly call ``.contiguous()`` because a non-contiguous weight
  silently slows the GEMM, so the pilot's dynamic-vs-static difference would have mixed a
  contiguity penalty into the "cost of switching". ``slice_mode="materialize"`` bounds
  that by caching contiguous slices for the widths actually used, and the difference
  between the two modes is reported as its own number rather than absorbed.
* The pilot could not separate the cost of *the switch* from the cost of the *steady
  state at the new width*, and kept no switch counter. ``SwitchController`` times
  ``apply()`` directly (host-side, ``perf_counter``) and can warm a width so the first
  call after a switch is measured deliberately instead of by accident.

The change that makes switching cheap at all is that a width change touches only one
attribute per layer; the expensive part, if any, is the shape-dependent kernel selection
on the *next* forward, which is why cold and warm states are separated everywhere.
"""
from __future__ import annotations

import time
import types

import torch
import torch.nn.functional as F

import build_worker
import latency_lib as lib
import switch_schedules as sched

WIDTH_FULL = sched.WIDTH_FULL
SLICE_MODES = ("view", "narrow", "materialize")


def _slice_weight(weight: torch.Tensor, dim: int, width: int, mode: str) -> torch.Tensor:
    """A view or a materialised contiguous slice of ``weight`` along ``dim``.

    ``gate``/``up`` are row slices (dim=0) and are already contiguous; ``down_proj`` is a
    column slice (dim=1) and is not. ``mode="materialize"`` returns a contiguous copy so
    the GEMM sees the same layout a static worker would; ``view``/``narrow`` keep the
    pilot's strided-view behaviour and differ only in the slicing API.
    """
    if width == weight.shape[dim]:
        return weight
    if mode == "narrow":
        base = torch.narrow(weight, dim, 0, width)
    else:
        base = weight[:width] if dim == 0 else weight[:, :width]
    if mode == "materialize":
        return base.contiguous()
    return base


def _switchable_forward(mlp, hidden_states: torch.Tensor) -> torch.Tensor:
    """Drop-in ``Gemma3nTextMLP.forward`` that honours ``mlp.active_width``.

    Kept byte-for-byte equivalent to the stock path at full width and to the preflight
    ``width_forward`` at any width: gate -> gaussian_topk -> act, times up, down-projected.
    """
    ctrl = mlp._switch_controller
    width = mlp.active_width
    gate_w = ctrl.slice_for(mlp, mlp.gate_proj.weight, 0, "gate_proj", width)
    up_w = ctrl.slice_for(mlp, mlp.up_proj.weight, 0, "up_proj", width)
    down_w = ctrl.slice_for(mlp, mlp.down_proj.weight, 1, "down_proj", width)
    gate = F.linear(hidden_states, gate_w)
    if mlp.activation_sparsity > 0.0:
        gate = ctrl.gaussian_topk(mlp, gate)
    activations = mlp.act_fn(gate)
    up = F.linear(hidden_states, up_w)
    return F.linear(activations * up, down_w)


class SwitchController:
    """Make one full-weight Gemma 3n text model serve any per-layer FFN width.

    The controller installs a shared ``forward`` on every ``Gemma3nTextMLP`` that reads
    ``mlp.active_width`` (the pilot's mechanism, made explicit), and exposes:

    * ``apply(plan)``       -- set all 35 layer widths (host-side; counted)
    * ``apply_timed(plan)`` -- the same, timed in milliseconds
    * ``materialize(plan)`` -- pre-slice contiguous weights (materialize mode only)
    * ``warm(plan, ids)``   -- run one forward so a later measurement is not cold
    * ``engage()/bypass()`` -- switch the whole model between the patched and the
                               original stock forward, so the dynamic *path* can be
                               compared against itself at full width (null control)
    """

    def __init__(self, model, *, slice_mode: str = "view", cache_slices: bool = True,
                 cache_sparsity_cutoff: bool = False, verbose: bool = True):
        if slice_mode not in SLICE_MODES:
            raise ValueError(f"slice_mode must be one of {SLICE_MODES}, got {slice_mode!r}")
        self.model = model
        self.layers = model.model.layers
        self.num_layers = len(self.layers)
        self.slice_mode = slice_mode
        self.cache_slices = bool(cache_slices)
        self.cache_sparsity_cutoff = bool(cache_sparsity_cutoff)
        self._cache = {}
        self._originals = {}
        self.n_switches = 0
        self.apply_times_ms = []
        self.engaged = False
        self.current = None
        self._install()
        if verbose:
            print(f"[dynamic] controller: {self.num_layers} layers, slice_mode={slice_mode}, "
                  f"cached_slices={self.cache_slices}, sparsity_cutoff_cache="
                  f"{self.cache_sparsity_cutoff}", flush=True)

    def _install(self) -> None:
        for idx, layer in enumerate(self.layers):
            mlp = layer.mlp
            mlp._switch_controller = self
            mlp._layer_index = idx
            if not hasattr(mlp, "active_width"):
                mlp.active_width = int(mlp.intermediate_size)
            # Stash the *stock* forward once, on the module. If a fresh controller were
            # built later without this, it would capture the already-patched forward as
            # "original" and ``bypass`` would silently be a no-op -- the exact kind of
            # confound this suite exists to avoid.
            if not hasattr(mlp, "_stock_forward"):
                mlp._stock_forward = mlp.forward
            self._originals[idx] = mlp._stock_forward
        self.engage()
        self.current = sched.WidthPlan.uniform(WIDTH_FULL, name="full")

    def engage(self) -> None:
        for layer in self.layers:
            layer.mlp.forward = types.MethodType(_switchable_forward, layer.mlp)
        self.engaged = True

    def bypass(self) -> None:
        """Restore the original stock forward (dynamic *path* off, widths ignored)."""
        for idx, layer in enumerate(self.layers):
            layer.mlp.forward = self._originals[idx]
        self.engaged = False

    # -- width selection ---------------------------------------------------- #
    def apply(self, plan: sched.WidthPlan) -> bool:
        if len(plan.widths) != self.num_layers:
            raise ValueError(f"plan has {len(plan.widths)} widths, model has {self.num_layers}")
        changed = self.current is None or plan.widths != self.current.widths
        for layer, width in zip(self.layers, plan.widths):
            layer.mlp.active_width = int(width)
        self.current = plan
        if changed:
            self.n_switches += 1
        return changed

    def apply_timed(self, plan: sched.WidthPlan) -> dict:
        started = time.perf_counter()
        changed = self.apply(plan)
        ms = 1000.0 * (time.perf_counter() - started)
        self.apply_times_ms.append(ms)
        return {"apply_ms": ms, "changed": bool(changed)}

    def materialize(self, plan: sched.WidthPlan) -> dict:
        """Apply ``plan`` and force each slice to exist as a contiguous buffer."""
        started = time.perf_counter()
        self.apply(plan)
        count = 0
        for layer, width in zip(self.layers, plan.widths):
            m = layer.mlp
            for attr, dim in (("gate_proj", 0), ("up_proj", 0), ("down_proj", 1)):
                self._cache_get(m, getattr(m, attr).weight, dim, attr, int(width))
                count += 1
        return {"materialize_ms": 1000.0 * (time.perf_counter() - started), "slices": count}

    # -- slice access ------------------------------------------------------- #
    def slice_for(self, mlp, weight, dim, attr, width):
        if self.slice_mode == "materialize" and self.cache_slices:
            return self._cache_get(mlp, weight, dim, attr, width)
        return _slice_weight(weight, dim, width, self.slice_mode)

    def _cache_get(self, mlp, weight, dim, attr, width):
        key = (mlp._layer_index, attr, int(width))
        cached = self._cache.get(key)
        if cached is None:
            cached = _slice_weight(weight, dim, width, "materialize")
            self._cache[key] = cached
        return cached

    # -- gaussian_topk with an optional precomputed cutoff ------------------ #
    def gaussian_topk(self, mlp, inputs: torch.Tensor) -> torch.Tensor:
        sparsity = mlp.activation_sparsity
        cached = getattr(mlp, "_std_multiplier", None)
        if self.cache_sparsity_cutoff and cached is not None:
            std_multiplier = cached
        else:
            normal = torch.distributions.normal.Normal(0.0, 1.0)
            std_multiplier = normal.icdf(
                torch.tensor(sparsity, dtype=torch.float32, device=inputs.device)
            ).type(inputs.dtype)
            if self.cache_sparsity_cutoff:
                mlp._std_multiplier = std_multiplier
        mean = torch.mean(inputs, dim=-1, keepdim=True)
        std = torch.std(inputs, dim=-1, keepdim=True, unbiased=False)
        return F.relu(inputs - (mean + std * std_multiplier))

    # -- warmup / accounting ------------------------------------------------ #
    def warm(self, plan: sched.WidthPlan, ids: torch.Tensor, steps: int = 1) -> None:
        self.apply(plan)
        with torch.inference_mode():
            for _ in range(max(1, int(steps))):
                self.model(input_ids=ids, use_cache=False, logits_to_keep=1)
        torch.cuda.synchronize()

    def cached_bytes(self) -> int:
        return sum(t.numel() * t.element_size() for t in self._cache.values())

    def describe(self) -> dict:
        return {"slice_mode": self.slice_mode, "cache_slices": self.cache_slices,
                "cache_sparsity_cutoff": self.cache_sparsity_cutoff,
                "num_layers": self.num_layers, "cached_slices": len(self._cache),
                "cached_bytes": self.cached_bytes(), "n_switches": self.n_switches,
                "engaged": self.engaged,
                "current_plan": None if self.current is None else self.current.name,
                "apply_times_ms": list(self.apply_times_ms)}


# --------------------------------------------------------------------------- #
# Model construction and logit comparison
# --------------------------------------------------------------------------- #
def build_switchable(dtype, statics=("small",), device: str = "cuda", verbose: bool = True,
                     slice_mode: str = "view", cache_slices: bool = True,
                     cache_sparsity_cutoff: bool = False):
    """Build ONE full-weight switchable model plus static reference workers, one parent load.

    The dynamic model is the ``large`` worker (every layer at 16384): slicing *down* from
    it reproduces each preset exactly, which is why a single weight set can emulate any
    width. Static workers for the requested ``statics`` presets are built from the same
    parent load so the run does not re-read the ~16 GiB checkpoint. Passing ``"large"`` in
    ``statics`` is refused: the dynamic worker *is* the large worker, and a second copy
    would only waste ~13.7 GiB.

    Returns ``(dynamic, controller, statics, tokenizer, infos)``.
    """
    statics = [p for p in statics if p]
    if "large" in statics:
        raise ValueError("do not request static 'large': the dynamic worker is the large worker")
    presets = ["large"] + statics
    if verbose:
        print(f"[dynamic] one parent load: presets={presets} dtype={dtype}", flush=True)
    workers, tokenizer, infos = build_worker.build_workers(presets, dtype, device, verbose=verbose)
    dynamic = workers.pop("large")
    controller = SwitchController(dynamic, slice_mode=slice_mode, cache_slices=cache_slices,
                                  cache_sparsity_cutoff=cache_sparsity_cutoff, verbose=verbose)
    static_workers = {p: workers[p] for p in statics}
    return dynamic, controller, static_workers, tokenizer, infos


def compare_logits(a: torch.Tensor, b: torch.Tensor) -> dict:
    """Numerical agreement between two logit tensors (the equivalence gate)."""
    diff = (a - b).abs()
    return {"max_abs_logit": float(diff.max()), "mean_abs_logit": float(diff.mean()),
            "same_argmax": bool(a.argmax(-1).item() == b.argmax(-1).item()),
            "finite": bool(torch.isfinite(a).all().item() and torch.isfinite(b).all().item())}


def model_dtype(model) -> torch.dtype:
    return next(model.parameters()).dtype


# --------------------------------------------------------------------------- #
# Scheduled generation: one request whose width may change every token
# --------------------------------------------------------------------------- #
def run_generation(timer, flusher, model, controller, prompt_ids, schedule,
                   new_tokens: int, flush: bool = True) -> dict:
    """One greedy generation whose FFN width is set from ``schedule`` per forward pass.

    ``schedule[0]`` is the prefill width; ``schedule[i+1]`` the width for decode step i.
    The switch itself is timed on the host *outside* the device timer, so per-step numbers
    are forward time only and the switch cost is reported separately.

    The cache is deliberately NOT flushed between steps: a real generation loop does not
    flush, and measuring exactly that loop is the point.
    """
    switching = controller is not None and schedule is not None
    if flush:
        flusher.flush()
    if switching:
        controller.apply(schedule[0])
    prefill_out, prefill_wall, prefill_gpu = timer.time(
        lambda: model(input_ids=prompt_ids, use_cache=True, logits_to_keep=1))
    cache = prefill_out.past_key_values
    step_input = prompt_ids[:, -1:]
    steps, switch_ms = [], []
    e2e = 0.0
    first_wall = None
    for i in range(int(new_tokens)):
        if switching and i + 1 < len(schedule):
            switch_ms.append(controller.apply_timed(schedule[i + 1])["apply_ms"])
        out, wall, gpu = timer.time(
            lambda c=cache, n=step_input: model(input_ids=n, past_key_values=c,
                                                use_cache=True, logits_to_keep=1))
        plan_name = (schedule[i + 1].name if i + 1 < len(schedule) else schedule[-1].name) \
            if switching else "static"
        steps.append({"index": i, "wall_ms": wall, "gpu_ms": gpu, "alpha_ms": wall - gpu,
                      "plan": plan_name})
        if i == 0:
            first_wall = wall
        e2e += wall
        step_input = out.logits[:, -1:].argmax(-1)
        cache = out.past_key_values
    return {"prefill_wall_ms": prefill_wall, "prefill_gpu_ms": prefill_gpu,
            "ttft_ms": prefill_wall + (first_wall or 0.0), "e2e_ms": prefill_wall + e2e,
            "steps": steps, "switch_ms": switch_ms,
            "prefill_plan": schedule[0].name if switching else "static"}
