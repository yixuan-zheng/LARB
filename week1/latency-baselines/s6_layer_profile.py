"""S6: per-layer attribution and the analytic ceiling on any achievable speedup.

Purpose in the ladder
---------------------
A width change touches exactly one of the ~13 compute units in a Gemma 3n decoder layer,
and only 3 of ~455 per-forward module invocations scale with it. S6 measures the size of
that slice of the pie, which converts every other scenario's null result into a number:

    ceiling_speedup = 1 / (1 - ffn_time_share * (1 - small_over_large_bytes))

With an FFN weight ratio of 0.714, an FFN time share of 0.60 caps the achievable speedup at
~1.21x however well dispatch overhead is removed. Reporting this prevents the suite from
chasing an effect that cannot exist at the size claimed.

What is measured
----------------
1. Per-layer FFN runtime (all 35 layers) via CUDA events around each ``layers[i].mlp``
   forward, for one prefill and one decode step. Overhead is ~70 event pairs per iteration;
   the *shares* are the deliverable and absolute values are reported as slightly inflated.
2. Non-FFN attribution: the same event method applied to ``self_attn``, ``altup``,
   ``laurel``, the per-layer input path and the norms, aggregated by module class.
3. A ``torch.profiler`` pass with CUDA activities, aggregating kernels into categories
   (matmul / elementwise / reduction / norm / softmax / other) so the machine-level story
   can be compared against the module-level one.

The two views are deliberately independent: if the module-level FFN share and the
matmul-kernel share disagree, that disagreement is itself informative and is recorded.
"""
from __future__ import annotations

import argparse
import collections

import torch

import build_worker
import latency_lib as lib
import latency_math as lm

SCENARIO = "s6_layer_profile"
MODULE_TAGS = (("mlp", "mlp"), ("self_attn", "self_attn"), ("altup", "altup"),
               ("laurel", "laurel"), ("per_layer_input", "per_layer_input_gate"),
               ("per_layer_projection", "per_layer_projection"), ("norm", "norm"))
#: Modules invoked through named methods instead of ``forward``. Gemma 3n calls
#: ``altup.predict``/``altup.correct`` directly, so forward hooks never fire for AltUp;
#: these methods are timed by wrapping, and their parts are summed back into the parent
#: tag in ``collect`` so the report shows a single ``altup`` share.
METHOD_TIMED = {"altup": ("predict", "correct")}
KERNEL_CATEGORIES = (("matmul", ("gemm", "gemv", "cutlass", "nvjet", "cublas", "mma")),
                     ("norm", ("norm", "rms")),
                     ("softmax", ("softmax",)),
                     ("reduction", ("reduce", "sum", "mean", "std")),
                     ("elementwise", ("elementwise", "vectorized", "pointwise")),
                     ("copy", ("copy", "cat", "contiguous", "fill")))


def tag_for(name: str):
    for tag, needle in MODULE_TAGS:
        if needle in name:
            return tag
    return None


def categorize(kernel_name: str):
    lowered = kernel_name.lower()
    for category, needles in KERNEL_CATEGORIES:
        if any(n in lowered for n in needles):
            return category
    return "other"


class ModuleTimer:
    """CUDA-event timing for selected submodules, indexed by (tag, layer, rep)."""

    def __init__(self, model, reps: int):
        self.events, self.handles, self._wrapped = {}, [], []
        layers = model.model.layers
        for layer_idx, layer in enumerate(layers):
            for name, module in layer.named_modules():
                if not name or "." in name:
                    continue  # only direct children of the decoder layer
                tag = tag_for(name)
                if tag is None:
                    continue
                if tag in METHOD_TIMED:
                    for method_name in METHOD_TIMED[tag]:
                        key = (f"{tag}:{method_name}", layer_idx)
                        self.events[key] = [(torch.cuda.Event(enable_timing=True),
                                             torch.cuda.Event(enable_timing=True))
                                            for _ in range(reps)]
                        self._wrap_method(module, method_name, key)
                    continue
                key = (tag, layer_idx)
                self.events[key] = [(torch.cuda.Event(enable_timing=True),
                                     torch.cuda.Event(enable_timing=True)) for _ in range(reps)]
                self.handles.append(module.register_forward_pre_hook(self._make_pre(key)))
                self.handles.append(module.register_forward_hook(self._make_post(key)))
        self.rep = 0
        # A hook pair only yields a duration if BOTH hooks fired; ``hits`` counts them so a
        # module whose hooks did not both run is skipped rather than passed to
        # ``elapsed_time`` (which would raise). AltUp is invoked as
        # ``altup.predict``/``altup.correct`` rather than ``altup(...)`` and is therefore
        # timed by method wrapping above, not by these forward hooks.
        self.hits = {}

    def _bump(self, key):
        self.hits[(key, self.rep)] = self.hits.get((key, self.rep), 0) + 1

    def _make_pre(self, key):
        def hook(module, inputs):
            self.events[key][self.rep][0].record()
            self._bump(key)
        return hook

    def _make_post(self, key):
        def hook(module, inputs, output):
            self.events[key][self.rep][1].record()
            self._bump(key)
        return hook

    def _wrap_method(self, module, method_name, key):
        """Time a bound method that bypasses ``forward`` (e.g. ``altup.predict``)."""
        original = getattr(module, method_name)

        def wrapper(*args, **kwargs):
            self.events[key][self.rep][0].record()
            self._bump(key)
            out = original(*args, **kwargs)
            self.events[key][self.rep][1].record()
            self._bump(key)
            return out

        # Store the plain function as an instance attribute: instance-dict lookups are not
        # descriptor-bound, so ``module.predict(x)`` calls ``wrapper(x)`` and the already
        # bound ``original(x)`` receives exactly one argument (MethodType would double-bind
        # self). ``close`` restores the bound method.
        setattr(module, method_name, wrapper)
        self._wrapped.append((module, method_name, original))

    def collect(self, reps: int) -> dict:
        """Median elapsed ms per (tag, layer), plus per-tag totals."""
        per_layer, invocations = {}, {}
        for (tag, layer_idx), pairs in self.events.items():
            # ``hits`` is keyed by (key, rep); a rep is usable only when both hooks fired.
            samples = sorted(pairs[r][0].elapsed_time(pairs[r][1])
                             for r in range(reps)
                             if self.hits.get(((tag, layer_idx), r), 0) >= 2)
            invocations.setdefault(tag, 0)
            # Both hooks bump, so a single invocation registers two hits; halve it so the
            # reported count is real invocations per pass (35 layers -> 35, 5 norms -> 175).
            invocations[tag] += self.hits.get(((tag, layer_idx), 0), 0) // 2
            if samples:
                per_layer.setdefault(tag, {})[layer_idx] = samples[len(samples) // 2]
        # Merge method-timed parts (``altup:predict`` + ``altup:correct``) into their parent
        # tag so the report shows one ``altup`` share rather than two fragments.
        merged_layer, merged_inv = {}, {}
        for tag, layers_map in per_layer.items():
            dest = merged_layer.setdefault(tag.split(":", 1)[0], {})
            for layer_idx, ms in layers_map.items():
                dest[layer_idx] = dest.get(layer_idx, 0.0) + ms
        for tag, count in invocations.items():
            base = tag.split(":", 1)[0]
            merged_inv[base] = merged_inv.get(base, 0) + count
        per_layer, invocations = merged_layer, merged_inv
        totals = {tag: sum(v.values()) for tag, v in per_layer.items()}
        return {"per_layer_median_ms": {t: {str(k): v for k, v in sorted(d.items())}
                                        for t, d in per_layer.items()},
                "per_tag_total_ms": totals, "per_tag_invocations": invocations,
                "tags_never_invoked": sorted(t for t in invocations if not per_layer.get(t))}

    def close(self):
        for module, method_name, original in self._wrapped:
            setattr(module, method_name, original)
        self._wrapped = []
        for handle in self.handles:
            handle.remove()
        self.handles = []


def profile_pass(worker, ids, cache, backend_step, label):
    """One torch.profiler pass; kernels aggregated into coarse categories."""
    for _ in range(2):
        backend_step()
    torch.cuda.synchronize()
    from torch.profiler import ProfilerActivity, profile
    with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
        backend_step()
        torch.cuda.synchronize()
    by_category = collections.Counter()
    rows = []
    for event in prof.key_averages():
        cuda_us = getattr(event, "device_time_total", None)
        if cuda_us is None:
            cuda_us = getattr(event, "cuda_time_total", 0)
        if not cuda_us:
            continue
        category = categorize(event.key)
        by_category[category] += cuda_us
        rows.append({"key": event.key, "category": category, "cuda_us": cuda_us,
                     "count": event.count})
    rows.sort(key=lambda r: -r["cuda_us"])
    total = sum(by_category.values()) or 1.0
    return {"label": label,
            "category_ms": {k: v / 1000.0 for k, v in by_category.most_common()},
            "category_share": {k: v / total for k, v in by_category.most_common()},
            "top_kernels": rows[:25], "total_cuda_ms": total / 1000.0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser, default_reps=5, default_warmup=2)
    parser.add_argument("--prompt-len", type=int, default=1024)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--prompt-offset", type=int, default=0)
    args = parser.parse_args()
    if not args.preset:
        args.preset = "small"
    if not args.peak_tflops and not args.peak_gbps:
        pass

    protocol = lib.prepare_runtime(args)
    peaks = lib.resolve_peaks(args, lib.device_info()["name"])
    record = lib.RunRecord(SCENARIO, args, lib.base_manifest(args, SCENARIO))
    record.set_manifest(protocol=protocol, peaks=peaks)
    record.set_protocol(warmup=args.warmup, reps=args.reps, prompt_len=args.prompt_len,
                        batch=args.batch, method="cuda_events_per_submodule + torch.profiler",
                        note=("event instrumentation adds ~70 event pairs per iteration; "
                              "treat shares as the result and absolutes as slightly inflated"),
                        prompt_offset=args.prompt_offset)
    if args.estimate_only:
        print(lib.estimate_wall_time(3, args.reps, args.warmup, 300.0))
        return

    record.set_extra("clock_ramp", lib.clock_ramp(args.clock_ramp_s))
    guard = lib.wait_for_sm_clock(args.min_sm_clock_mhz)
    record.set_extra("clock_guard", guard)
    if args.strict_clock and guard.get("ok") is False:
        raise SystemExit(f"SM clock guard failed: {guard}")

    print(f"[s6] building worker: {args.preset}", flush=True)
    worker, tokenizer, info = build_worker.build_worker(args.preset, lib.dtype_of(args))
    lib.reset_peak_memory()
    spec = lib.arch_spec_from_config(worker.config, model=worker)
    widths = list(spec.widths)
    record.set_extra("worker", info)
    ids, digest = lib.build_prompt_ids(tokenizer, args.prompt_len, args.prompt_offset)
    ids = ids.repeat(args.batch, 1).contiguous().to("cuda")
    one_id = lib.next_token_id(tokenizer, args.prompt_offset).repeat(args.batch, 1).to("cuda")
    record.set_extra("prompt_sha256", {str(args.prompt_len): digest})

    dtype_bytes = lib.DTYPE_BYTES[args.dtype]
    harness = lib.Harness(args)
    out = {}
    with torch.inference_mode():
        dec_cache = worker(input_ids=ids, use_cache=True, logits_to_keep=1).past_key_values
        # --- per-module event attribution, decode then prefill ------------------- #
        for label, step_fn in (("decode", lambda: worker(input_ids=one_id,
                                                         past_key_values=dec_cache,
                                                         use_cache=True, logits_to_keep=1)),
                               ("prefill", lambda: worker(input_ids=ids, use_cache=True,
                                                          logits_to_keep=1))):
            timer = ModuleTimer(worker, args.reps)
            step_wall = []
            try:
                for rep in range(args.reps):
                    timer.rep = rep
                    harness.flush()
                    torch.cuda.synchronize()
                    start = torch.cuda.Event(enable_timing=True)
                    end = torch.cuda.Event(enable_timing=True)
                    start.record()
                    step_fn()
                    end.record()
                    torch.cuda.synchronize()
                    step_wall.append(start.elapsed_time(end))
            finally:
                timer.close()
            attribution = timer.collect(args.reps)
            step_ms = sorted(step_wall)[len(step_wall) // 2]
            tags = dict(attribution["per_tag_total_ms"])
            ffn_ms = tags.get("mlp", 0.0)
            ffn_share = (ffn_ms / step_ms) if step_ms else None
            attributed_ms = sum(tags.values())
            # Two denominators. step_ms includes the instrumentation's own hook cost
            # (~20 ms here) and therefore understates the share; attributed_ms is the sum
            # of the timed modules, so ffn_time_share is self-consistent and is what the
            # ceiling uses. Both are published.
            ffn_share_attributed = (ffn_ms / attributed_ms) if attributed_ms else None
            ratio = lm.ffn_weight_bytes(spec, widths, 2) / lm.ffn_weight_bytes(
                spec, [16384] * spec.num_layers, 2)
            # Width slicing removes 28.6% of FFN weights (small vs large: 5.03/7.05 GiB), so
            # the ceiling this preset's own measured FFN share implies for a small-vs-large
            # comparison is 1 / (1 - ffn_share * 0.286). This is well defined for every
            # preset, including large, whose value is the one that pairs with the measured
            # small-vs-large ratio. The previous version scaled by each preset's own weight
            # ratio, which made large's ceiling trivially 1.0 and read as "no headroom".
            width_reduction = 1.0 - (lm.ffn_weight_bytes(spec, [8192] * 20 + [16384] * 15, 2)
                                     / lm.ffn_weight_bytes(spec, [16384] * spec.num_layers, 2))
            out[label] = {"step_gpu_ms": step_ms, "step_gpu_ms_samples": step_wall,
                          "per_tag_total_ms": tags,
                          "per_tag_share": {t: (v / step_ms if step_ms else None)
                                            for t, v in tags.items()},
                          "ffn_total_ms": ffn_ms, "attributed_total_ms": attributed_ms,
                          "ffn_time_share_of_step": ffn_share,
                          "ffn_time_share": ffn_share_attributed,
                          "ffn_weight_ratio_small_over_large": ratio,
                          "width_reduction_fraction": width_reduction,
                          "in_scope_fraction": ((ffn_share_attributed * width_reduction)
                                                if ffn_share_attributed else None),
                          "ceiling_speedup_if_ffn_free_portion": (
                              1.0 / (1.0 - ffn_share_attributed * width_reduction)
                              if ffn_share_attributed else None),
                          "per_tag_invocations": attribution["per_tag_invocations"],
                          "tags_never_invoked": attribution["tags_never_invoked"],
                          "per_layer_median_ms": attribution["per_layer_median_ms"]}
            record.set_extra("attribution", out)
            print(f"[s6] {label}: step={step_ms:.2f}ms attributed={attributed_ms:.2f}ms "
                  f"ffn={ffn_ms:.2f}ms share_attr="
                  f"{None if ffn_share_attributed is None else round(ffn_share_attributed, 3)} "
                  f"ceiling={out[label]['ceiling_speedup_if_ffn_free_portion']} "
                  f"tags={ {t: round(v, 2) for t, v in sorted(tags.items())} }",
                  flush=True)
            if label == "decode":
                dec_cache = worker(input_ids=ids, use_cache=True,
                                   logits_to_keep=1).past_key_values

        # --- independent kernel-level view -------------------------------------- #
        out["profiler"] = {
            "prefill": profile_pass(worker, ids, None,
                                    lambda: worker(input_ids=ids, use_cache=True,
                                                   logits_to_keep=1), "prefill"),
            "decode": profile_pass(worker, ids, dec_cache,
                                   lambda: worker(input_ids=one_id, past_key_values=dec_cache,
                                                  use_cache=True, logits_to_keep=1), "decode"),
        }
        record.set_extra("attribution", out)
        record.set_extra("peak_memory", lib.peak_memory_snapshot())
        record.set_extra("clocks_at_end", lib.clocks_snapshot())

    record.complete()
    print("PASS s6_layer_profile", flush=True)


if __name__ == "__main__":
    main()
