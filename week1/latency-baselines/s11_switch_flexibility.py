"""S11: the flexibility advantage of one switchable weight set, and what it costs in VRAM.

Purpose in the extension
------------------------
S8-S10 measure the *cost* of dynamic switching. This scenario measures the *advantage*
that the static suite cannot even express: a single resident copy of the E4B text weights
can serve any per-layer FFN width on any iteration, whereas the static approach needs a
separate resident model (or a reload) for every width it wants available.

Concretely it reports:

* **weights per option** -- the measured resident bytes for the dynamic (full) model and
  for the static small/medium workers, off the live modules.
* **the real tradeoff, stated both ways** -- the dynamic model holds the *wide* weights
  (14.75 GB) and therefore uses ~2.01 GB more than a static small model; but a static
  setup that wants both widths resident needs two models (27.5 GB). Dynamic switching buys
  the second width for free at rest.
* **capacity** -- max batch before OOM at a short and a long context, for the dynamic model
  (wide weights) vs the static small worker, which is the concrete cost of flexibility.
* **retarget cost** -- the host-side time to re-point the dynamic model at another width
  (a few microseconds, from ``apply``), against the tens of seconds a reload would take.

A mixed-batch policy (different requests wanting different widths in one step) is out of
scope: this mechanism holds one width for the whole batch per iteration, and that is stated
rather than implied.
"""
from __future__ import annotations

import argparse
import gc
import json
import subprocess
import sys

import torch

import build_worker
import dynamic_lib as dyn
import latency_lib as lib
import latency_math as lm
import switch_schedules as sched

SCENARIO = "s11_switch_flexibility"


def max_batch_before_oom(model, ids_fn, start: int = 1, cap: int = 512) -> dict:
    """Double the batch until an allocation fails; return the last success (as in S7)."""
    last_ok, failure, batch = 0, None, start
    while batch <= cap:
        torch.cuda.empty_cache()
        try:
            ids = ids_fn(batch)
            with torch.inference_mode():
                out = model(input_ids=ids, use_cache=True, logits_to_keep=1)
            del out
            torch.cuda.empty_cache()
            last_ok = batch
            batch *= 2
        except torch.cuda.OutOfMemoryError as exc:
            failure = repr(exc).splitlines()[0] if str(exc) else "OutOfMemoryError"
            break
        except RuntimeError as exc:
            failure = repr(exc)[:200]
            break
    return {"max_batch": last_ok, "first_failing_batch": batch, "failure": failure}


def capacity_probe(args) -> None:
    """Measure one option's max batch with only that model resident, then print JSON.

    Run as a child process (see ``run_isolated_capacity``) so the parent never has to
    keep more than one model in memory.
    """
    contexts = [int(x) for x in args.capacity_contexts.split(",") if x.strip()]
    preset = "large" if args.capacity_only == "dynamic" else args.capacity_only
    lib.prepare_runtime(args)
    if args.clock_ramp_s > 0:
        lib.clock_ramp(args.clock_ramp_s)
    worker, tokenizer, _info = build_worker.build_worker(preset, lib.dtype_of(args),
                                                         verbose=False)
    out = {}
    with torch.inference_mode():
        for ctx_len in contexts:
            base, _ = lib.build_prompt_ids(tokenizer, max(1, ctx_len), args.prompt_offset)

            def ids_fn(batch_size, _i=base):
                return _i.repeat(batch_size, 1).contiguous().to("cuda")

            out[str(ctx_len)] = max_batch_before_oom(worker, ids_fn, cap=args.capacity_cap)
    print("S11_CAPACITY_JSON=" + json.dumps(out), flush=True)


def run_isolated_capacity(args, options, contexts) -> dict:
    """Capacity per option, each measured in its own process.

    S11 keeps the dynamic model and every static reference resident, so a naive sweep
    measures the *combined* footprint (the cap is set by the other models, not by the FFN
    width under test). Parking the others on the CPU is impossible here -- this
    allocation's host-memory cgroup is ~16 GiB -- so isolation is by process instead:
    each option is probed with only its own model ever resident.
    """
    out = {}
    for caption, option in options:
        cmd = [sys.executable, "-u", __file__, "--capacity-only", option,
               "--capacity-cap", str(args.capacity_cap),
               "--capacity-contexts", ",".join(str(c) for c in contexts),
               "--prompt-offset", str(args.prompt_offset),
               "--clock-ramp-s", "0", "--min-sm-clock-mhz", "0"]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        payload = next((line for line in reversed(proc.stdout.splitlines())
                        if line.startswith("S11_CAPACITY_JSON=")), None)
        if payload is None:
            out[caption] = {"error": "capacity subprocess produced no result",
                            "returncode": proc.returncode,
                            "stderr_tail": (proc.stderr or "").splitlines()[-4:]}
            print(f"[s11] capacity subprocess '{option}' failed rc={proc.returncode}", flush=True)
            continue
        for ctx_str, result in json.loads(payload.split("=", 1)[1]).items():
            out[f"{caption}_L{ctx_str}"] = result
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=5, default_warmup=2)
    parser.add_argument("--statics", default="small,medium")
    parser.add_argument("--slice-mode", default="view", choices=list(dyn.SLICE_MODES))
    parser.add_argument("--capacity-contexts", default="1,2048")
    parser.add_argument("--capacity-cap", type=int, default=64)
    parser.add_argument("--capacity-only", default=None,
                        choices=["dynamic", "small", "medium"],
                        help="internal: measure just this option's capacity and print JSON")
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    statics = [p.strip() for p in args.statics.split(",") if p.strip()]
    capacity_contexts = [int(x) for x in args.capacity_contexts.split(",") if x.strip()]
    if args.capacity_only:
        capacity_probe(args)
        return

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(statics=statics, slice_mode=args.slice_mode,
                        capacity_contexts=capacity_contexts, capacity_cap=args.capacity_cap,
                        prompt_offset=args.prompt_offset,
                        note="one dynamic model (wide weights) vs static workers; "
                             "mixed-batch policies are out of scope")
    if args.estimate_only:
        print(lib.estimate_wall_time(len(capacity_contexts) * (1 + len(statics)),
                                     1, 0, 60.0))
        return

    print("[s11] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s11] building switchable model (statics={statics})", flush=True)
    dynamic, controller, static_workers, tokenizer, infos = dyn.build_switchable(
        lib.dtype_of(args), statics=statics, slice_mode=args.slice_mode)
    lib.reset_peak_memory()
    record.set_extra("dynamic_describe", controller.describe())
    record.set_extra("workers", infos)
    widths_map = sched.load_preset_widths()
    plans = {p: sched.WidthPlan.from_preset(p, widths_map)
             for p in ("small", "medium", "large")}
    record.set_extra("peak_after_load", lib.peak_memory_snapshot())

    weights = {"dynamic_full": infos["large"]["param_bytes"]["total"]}
    for preset in statics:
        weights[f"static_{preset}"] = infos[preset]["param_bytes"]["total"]
    static_small = weights.get("static_small", weights["dynamic_full"])
    weights["static_small_plus_large_full"] = static_small + weights["dynamic_full"]
    analytic = {
        "dynamic_minus_static_small_bytes": weights["dynamic_full"] - static_small,
        "static_two_model_minus_dynamic_bytes": (weights["static_small_plus_large_full"]
                                                 - weights["dynamic_full"]),
        "interpretation": ("dynamic holds the wide weights (a cost of "
                           "dynamic_minus_static_small vs a small-only static model) and "
                           "in exchange needs no second model to serve both widths "
                           "(static_two_model_minus_dynamic)"),
    }

    retarget = {}
    with torch.inference_mode():
        # Retarget cost: alternate every apply so each one actually changes the width.
        # Done before the capacity probes, which need the GPU to themselves.
        controller.apply(plans["large"])
        apply_ms = []
        for i in range(200):
            apply_ms.append(controller.apply_timed(
                plans["small"] if i % 2 == 0 else plans["large"])["apply_ms"])
        retarget = {
            "apply_us": lm.summarize([v * 1000.0 for v in apply_ms]),
            "load_seconds": {p: infos[p]["load_seconds"] for p in ("large",) + tuple(statics)},
        }
        retarget["apply_vs_reload_ratio"] = {
            p: (retarget["apply_us"]["median"] * 1e-6) / max(infos[p]["load_seconds"], 1e-9)
            for p in ("large",) + tuple(statics)}

    # Capacity per option, isolated by process: the host cgroup (~16 GiB) is far too small
    # to park the other models on the CPU, and this GPU cannot hold a fourth model, so the
    # resident models are released first and each option is probed in its own process.
    del controller, dynamic, static_workers
    gc.collect()
    torch.cuda.empty_cache()
    print("[s11] capacity: one process per option ...", flush=True)
    capacity = run_isolated_capacity(
        args, [("dynamic", "dynamic")] + [(f"static_{p}", p) for p in statics],
        capacity_contexts)
    record.set_extra("capacity", capacity)
    for ctx_len in capacity_contexts:
        print(f"[s11] ctx={ctx_len}: " + ", ".join(
            f"{name}={capacity.get(f'{name}_L{ctx_len}', {}).get('max_batch')}"
            for name in ["dynamic"] + [f"static_{p}" for p in statics]), flush=True)

    switching = {
        "weights_bytes": weights,
        "weights_gib": {k: v / 1024**3 for k, v in weights.items()},
        "analytic": analytic,
        "capacity": capacity,
        "retarget": retarget,
        "n_presets_emulated": len(plans),
        "preset_names": sorted(plans),
        "capacity_cap": args.capacity_cap,
        "peak_after_load": record.data.get("peak_after_load"),
    }
    record.set_extra("switching", switching)
    record.set_extra("peak_memory", lib.peak_memory_snapshot())
    record.set_extra("clocks_at_end", lib.clocks_snapshot())
    record.complete()
    print("PASS s11_switch_flexibility", flush=True)


if __name__ == "__main__":
    main()
