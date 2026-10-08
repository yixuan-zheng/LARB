"""S8: validate the dynamic switching mechanism and price its inherent overhead.

Purpose in the extension
------------------------
This is the gate, the dynamic analogue of S0. The static profile (S0-S7) is only
interpretable because S0 first proved the instrument recovers a known 2x difference and
invents none of its own. Dynamic switching needs the same guarantees before any schedule
result can be trusted:

  * **equivalence** -- a dynamic model set to width W must produce the *same logits* as a
    physically static W worker (and, at full width, as the untouched stock forward);
  * **a null control** -- two independent dynamic conditions at the same width with no
    switch must land `within_noise`.

On top of those gates it measures the quantities every later scenario is read in units of:

1. ``switch_op_us``  -- the host-side cost of changing the width on all 35 layers. Expected
                        to be microseconds (35 attribute writes); if it were not, no
                        schedule could ever pay for itself.
2. ``tax``           -- dynamic-at-W vs static-at-W on identical prefill and decode
                        workloads, per ``slice_mode``. ``view`` is the pilot's strided-view
                        path; ``materialize`` caches contiguous slices. The gap between
                        them is the *contiguity tax* the pilot would otherwise have
                        mislabelled as "the cost of switching".
3. ``cold_switch``   -- the first forward after a width change vs a warmed steady state at
                        that width (prefill only; decode is always warm because building
                        the cache runs a forward first).

A prefill workload (default 512 x batch 4) is used because S2/S5 established it as the
regime where a width change actually moves the needle; the decode workload (default 512
ctx, batch 1) is included because S1/S3 established it as the regime where nothing moves,
which is where a tax would be most visible relative to the effect.
"""
from __future__ import annotations

import argparse

import torch

import dynamic_lib as dyn
import latency_lib as lib
import latency_math as lm
import switch_schedules as sched

SCENARIO = "s8_switch_mechanism"
TOLERANCE_MAX_ABS_LOGIT = 0.05
BENCH_APPLIES = 200


def bench_apply(ctrl, plan, other, n: int = BENCH_APPLIES) -> list:
    """Time ``apply`` when the plan *changes* every call, alternating against ``other``."""
    ctrl.apply(other)
    values = []
    for _ in range(n):
        values.append(ctrl.apply_timed(plan)["apply_ms"])
        ctrl.apply_timed(other)
    return values


def bench_materialize(ctrl, plan, n: int = 5) -> list:
    """Time ``materialize`` (contiguous slicing of all 35 layers) from a cold cache."""
    values = []
    for _ in range(n):
        ctrl._cache.clear()
        values.append(ctrl.materialize(plan)["materialize_ms"])
    return values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=30, default_warmup=8)
    parser.add_argument("--statics", default="small,medium",
                        help="static reference presets; 'large' is refused (the dynamic "
                             "worker is the large worker)")
    parser.add_argument("--slice-modes", default="view,materialize",
                        help="comma-separated subset of view,narrow,materialize")
    parser.add_argument("--prompt-len", type=int, default=512)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--ctx-len", type=int, default=512)
    parser.add_argument("--prompt-offset", type=int, default=0)
    parser.add_argument("--cache-sparsity-cutoff", action="store_true")
    args = parser.parse_args()
    slice_modes = [m.strip() for m in args.slice_modes.split(",") if m.strip()]
    for m in slice_modes:
        if m not in dyn.SLICE_MODES:
            raise SystemExit(f"unknown slice mode {m!r}; expected one of {dyn.SLICE_MODES}")
    statics = [p.strip() for p in args.statics.split(",") if p.strip()]

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, statics=statics,
                        slice_modes=slice_modes, prompt_len=args.prompt_len, batch=args.batch,
                        ctx_len=args.ctx_len, cache_sparsity_cutoff=args.cache_sparsity_cutoff,
                        interleaved=True, shuffled=True, flush_l2=args.flush_l2,
                        flush_mb=args.flush_mb, prompt_offset=args.prompt_offset,
                        tolerance_max_abs_logit=TOLERANCE_MAX_ABS_LOGIT)
    if args.estimate_only:
        print(lib.estimate_wall_time(2 * len(slice_modes) * (len(statics) + 4),
                                     args.reps, args.warmup, 180.0))
        return

    print("[s8] clock ramp ...", flush=True)
    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s8] building switchable model (statics={statics})", flush=True)
    dynamic, ctrl, static_workers, tokenizer, infos = dyn.build_switchable(
        lib.dtype_of(args), statics=statics, slice_mode=slice_modes[0],
        cache_sparsity_cutoff=args.cache_sparsity_cutoff)
    lib.reset_peak_memory()
    record.set_extra("dynamic_describe", ctrl.describe())
    record.set_extra("workers", infos)
    record.set_extra("dynamic_param_bytes", infos["large"]["param_bytes"])

    widths_map = sched.load_preset_widths()
    plans = {p: sched.WidthPlan.from_preset(p, widths_map)
             for p in ("small", "medium", "large")}

    ids, digest = lib.build_prompt_ids(tokenizer, 16, args.prompt_offset)
    ids = ids.to("cuda")
    record.set_extra("equiv_prompt_sha256", digest)

    switching = {}
    with torch.inference_mode():
        # -- equivalence gate (logits) -------------------------------------- #
        ctrl.bypass()
        stock_large = dynamic(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float().clone()
        ctrl.engage()
        equiv = {"tolerance_max_abs_logit": TOLERANCE_MAX_ABS_LOGIT, "per_width": {}}
        for preset in ("large",) + tuple(statics):
            ctrl.apply(plans[preset])
            dyn_logits = dynamic(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
            if preset == "large":
                ref, ref_name = stock_large, "dynamic_stock_full_width"
            else:
                ref = static_workers[preset](input_ids=ids, use_cache=False,
                                             logits_to_keep=1).logits.float()
                ref_name = f"static_{preset}"
            cmp = dyn.compare_logits(dyn_logits, ref)
            cmp["reference"] = ref_name
            cmp["passed"] = bool(cmp["finite"] and cmp["same_argmax"]
                                 and cmp["max_abs_logit"] <= TOLERANCE_MAX_ABS_LOGIT)
            equiv["per_width"][preset] = cmp
            print(f"[s8] equivalence dyn_{preset} vs {ref_name}: "
                  f"max_abs={cmp['max_abs_logit']:.3e} argmax={cmp['same_argmax']} "
                  f"passed={cmp['passed']}", flush=True)
        mixed = sched.WidthPlan.per_layer(
            "mixed", [8192 if i % 3 == 0 else 16384 for i in range(sched.NUM_LAYERS)])
        ctrl.apply(mixed)
        mixed_log = dynamic(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
        equiv["mixed_plan"] = {"finite": bool(torch.isfinite(mixed_log).all().item()),
                               **mixed.describe()}
        ctrl.apply(plans["large"])
        switching["equivalence"] = equiv

        # -- decode-path equivalence (with a live KV cache) ------------------ #
        # The block above uses ``use_cache=False``. Decode is where the schedules (s9/s10)
        # actually switch, so prove the switchable path matches the static worker once a
        # cache exists too: prefill to build the cache at width W, then compare the
        # next-token logits. Each width gets a *fresh* cache so no comparison inherits a
        # cache mutated by a previous one.
        eq_dec = {"tolerance_max_abs_logit": TOLERANCE_MAX_ABS_LOGIT, "per_width": {}}
        ctrl.bypass()
        stock_prefill = dynamic(input_ids=ids, use_cache=True, logits_to_keep=1)
        stock_dec = dynamic(input_ids=ids[:, -1:], past_key_values=stock_prefill.past_key_values,
                            use_cache=True, logits_to_keep=1).logits.float()
        for preset in ("large",) + tuple(statics):
            ctrl.engage()
            ctrl.apply(plans[preset])
            dyn_prefill = dynamic(input_ids=ids, use_cache=True, logits_to_keep=1)
            dyn_dec = dynamic(input_ids=ids[:, -1:], past_key_values=dyn_prefill.past_key_values,
                              use_cache=True, logits_to_keep=1).logits.float()
            if preset == "large":
                ref, ref_name = stock_dec, "dynamic_stock_full_width_decode"
            else:
                ref_prefill = static_workers[preset](input_ids=ids, use_cache=True,
                                                     logits_to_keep=1)
                ref = static_workers[preset](input_ids=ids[:, -1:],
                                             past_key_values=ref_prefill.past_key_values,
                                             use_cache=True, logits_to_keep=1).logits.float()
                ref_name = f"static_{preset}_decode"
            cmp = dyn.compare_logits(dyn_dec, ref)
            cmp["reference"] = ref_name
            cmp["passed"] = bool(cmp["finite"] and cmp["same_argmax"]
                                 and cmp["max_abs_logit"] <= TOLERANCE_MAX_ABS_LOGIT)
            eq_dec["per_width"][preset] = cmp
            print(f"[s8] decode-equivalence dyn_{preset} vs {ref_name}: "
                  f"max_abs={cmp['max_abs_logit']:.3e} argmax={cmp['same_argmax']} "
                  f"passed={cmp['passed']}", flush=True)
        ctrl.apply(plans["large"])
        switching["equivalence_decode"] = eq_dec

        # -- switch-operation microbench ------------------------------------ #
        apply_us, mat_ms = {}, {}
        for preset in ("large",) + tuple(statics):
            other = plans["small"] if preset == "large" else plans["large"]
            apply_us[preset] = lm.summarize([v * 1000.0 for v in
                                             bench_apply(ctrl, plans[preset], other)])
        switching["switch_op_us"] = apply_us
        for mode in slice_modes:
            ctrl.slice_mode = mode
            ctrl._cache.clear()
            mat_ms[mode] = {preset: lm.summarize(bench_materialize(ctrl, plans[preset]))
                            for preset in ("large",) + tuple(statics)}
        ctrl.slice_mode = slice_modes[0]
        ctrl._cache.clear()
        switching["materialize_ms"] = mat_ms
        print("[s8] switch-op median us: "
              f"{ {k: round(v['median'], 2) for k, v in apply_us.items()} }", flush=True)

    prompt, pdigest = lib.build_prompt_ids(tokenizer, args.prompt_len, args.prompt_offset)
    prompt = prompt.repeat(args.batch, 1).contiguous().to("cuda")
    ctx_prompt, cdigest = lib.build_prompt_ids(tokenizer, args.ctx_len, args.prompt_offset)
    ctx_prompt = ctx_prompt.repeat(args.batch, 1).contiguous().to("cuda")
    token = lib.next_token_id(tokenizer, args.prompt_offset).repeat(args.batch, 1).to("cuda")
    record.set_extra("prompt_sha256", {str(args.prompt_len): pdigest, str(args.ctx_len): cdigest})

    harness = lib.Harness(args)
    record.set_extra("flusher", harness.flusher.describe())

    def set_mode(cfg):
        if cfg["model"] == "dynamic":
            if cfg["mode"] == "stock":
                ctrl.bypass()
            else:
                ctrl.engage()
                if cfg.get("plan"):
                    ctrl.apply(plans[cfg["plan"]])

    def model_for(cfg):
        return dynamic if cfg["model"] == "dynamic" else static_workers[cfg["preset"]]

    def make_configs(workload):
        cfgs = [{"key": "stock_large", "workload": workload, "model": "dynamic",
                 "mode": "stock", "plan": None, "preset": "large"}]
        for p in ("large",) + tuple(statics):
            cfgs.append({"key": f"dyn_{p}", "workload": workload, "model": "dynamic",
                         "mode": "dyn", "plan": p, "preset": p})
        for p in statics:
            cfgs.append({"key": f"static_{p}", "workload": workload, "model": "static",
                         "mode": "stock", "plan": None, "preset": p})
        for dup in ("a", "b"):
            cfgs.append({"key": f"null_{dup}", "workload": workload, "model": "dynamic",
                         "mode": "dyn", "plan": "small", "preset": "small"})
        return cfgs

    def run_workload(workload, cfgs, warmup, reps):
        if workload == "prefill":
            def prepare(cfg):
                set_mode(cfg)
                return None

            def step(cfg, state):
                return model_for(cfg)(input_ids=prompt, use_cache=True, logits_to_keep=1)
        else:
            def prepare(cfg):
                set_mode(cfg)
                out = model_for(cfg)(input_ids=ctx_prompt, use_cache=True, logits_to_keep=1)
                return out.past_key_values

            def step(cfg, state):
                return model_for(cfg)(input_ids=token, past_key_values=state,
                                      use_cache=True, logits_to_keep=1)
        return harness.sweep(cfgs, prepare, step, warmup, reps, record=record)

    tax, null = {"prefill": {}, "decode": {}}, {}
    with torch.inference_mode():
        for mode in slice_modes:
            ctrl.slice_mode = mode
            ctrl._cache.clear()
            for workload in ("prefill", "decode"):
                cfgs = make_configs(workload)
                print(f"[s8] tax {workload} slice_mode={mode}: {args.warmup}w+{args.reps}r "
                      f"x {len(cfgs)} conds", flush=True)
                samples = run_workload(workload, cfgs, args.warmup, args.reps)
                summary = lib.summarize_samples(samples)
                record.set_summary(f"{workload}__{mode}", summary)
                entry = tax[workload].setdefault(mode, {})
                for p in statics:
                    dd, ss = summary[f"dyn_{p}"]["gpu_ms"], summary[f"static_{p}"]["gpu_ms"]
                    v = lib.compare_pairs(samples, f"static_{p}", f"dyn_{p}",
                                          metric="gpu_ms", seed=args.seed)
                    v["tax_pct"] = 100.0 * (dd["median"] - ss["median"]) / ss["median"]
                    v["dynamic_median_ms"], v["static_median_ms"] = dd["median"], ss["median"]
                    v["interpretation"] = "dynamic_at_W vs static_W (mechanism tax)"
                    entry[f"dyn_{p}_vs_static_{p}"] = v
                dl, sl = summary["dyn_large"]["gpu_ms"], summary["stock_large"]["gpu_ms"]
                v = lib.compare_pairs(samples, "stock_large", "dyn_large",
                                      metric="gpu_ms", seed=args.seed)
                v["tax_pct"] = 100.0 * (dl["median"] - sl["median"]) / sl["median"]
                v["dynamic_median_ms"], v["stock_median_ms"] = dl["median"], sl["median"]
                v["interpretation"] = "dynamic path at full width vs stock forward (path tax)"
                entry["dyn_large_vs_stock_large"] = v
                if mode == slice_modes[0]:
                    nv = lib.compare_pairs(samples, "null_a", "null_b",
                                           metric="gpu_ms", seed=args.seed)
                    nv["expected"] = "within_noise"
                    nv["passed"] = bool(not nv["appreciable"])
                    null[workload] = nv
    switching["tax"] = tax
    switching["null"] = null

    # -- cold-switch penalty (prefill: decode is always warm) ---------------- #
    cold = {}
    with torch.inference_mode():
        ctrl.slice_mode = slice_modes[0]
        ctrl._cache.clear()
        cfgs = []
        for p in ("large",) + tuple(statics):
            cfgs.append({"key": f"warm_{p}", "plan": p, "kind": "warm"})
            cfgs.append({"key": f"cold_{p}", "plan": p, "kind": "cold"})

        def prepare_cold(cfg):
            ctrl.engage()
            p = cfg["plan"]
            other = "small" if p == "large" else "large"
            if cfg["kind"] == "warm":
                ctrl.apply(plans[p])
                ctrl.warm(plans[p], prompt)
            else:
                ctrl.apply(plans[other])
                ctrl.warm(plans[other], prompt)   # leave a *different* shape last ...
                ctrl.apply(plans[p])              # ... then switch to p with no p-forward
            return None

        def step_cold(cfg, state):
            return dynamic(input_ids=prompt, use_cache=True, logits_to_keep=1)

        print(f"[s8] cold-switch prefill: {args.reps} reps x {len(cfgs)} conds", flush=True)
        samples = harness.sweep(cfgs, prepare_cold, step_cold, 0, args.reps, record=record)
        summary = lib.summarize_samples(samples)
        record.set_summary("cold_switch", summary)
        for p in ("large",) + tuple(statics):
            w, c = summary[f"warm_{p}"]["gpu_ms"], summary[f"cold_{p}"]["gpu_ms"]
            v = lib.compare_pairs(samples, f"warm_{p}", f"cold_{p}", metric="gpu_ms", seed=args.seed)
            v["cold_minus_warm_pct"] = 100.0 * (c["median"] - w["median"]) / w["median"]
            v["cold_median_ms"], v["warm_median_ms"] = c["median"], w["median"]
            v["interpretation"] = "first forward after a switch vs warmed steady state"
            cold[p] = v
    switching["cold_switch"] = cold

    record.set_extra("dynamic_describe_final", ctrl.describe())
    record.set_extra("switching", switching)
    record.set_extra("peak_memory", lib.peak_memory_snapshot())
    record.set_extra("clocks_at_end", lib.clocks_snapshot())
    record.complete()

    gate = (all(v["passed"] for v in switching["equivalence"]["per_width"].values())
            and all(v["passed"] for v in switching["equivalence_decode"]["per_width"].values()))
    null_ok = all(v["passed"] for v in switching["null"].values())
    if not gate:
        raise SystemExit("FAIL s8_switch_mechanism: dynamic != static at some width "
                         "(single forward or cached decode)")
    if not null_ok:
        raise SystemExit("FAIL s8_switch_mechanism: null control registered a difference")
    print("PASS s8_switch_mechanism", flush=True)


if __name__ == "__main__":
    main()
