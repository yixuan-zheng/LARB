"""Statically extract a Gemma 3n text sub-model at one FFN width per layer.

A worker is a real, independent ``Gemma3nForCausalLM``: the FFN hidden dimension comes
from the Google slicing preset and the E4B tensors are physically sliced
(``gate/up_proj[:W]``, ``down_proj[:, :W]``) and copied in. No view into the parent is
retained, so the parent can be freed and measured VRAM belongs to the worker alone.
This is the unit under test for the static scenarios (s0-s7); the dynamic-switching
extension (s8-s11) instead keeps the full E4B weights resident and slices at call time
(see ``dynamic_lib``).

Why text-only
-------------
The multimodal ``Gemma3nForConditionalGeneration`` peaks at ~15.6 GB on load (see
``preflight/results/pace_pretrained_results.json``) because of the vision and audio
towers, which do no work in a text latency profile and would consume exactly the VRAM
the large-batch and long-context arms need.

Why equivalence is not re-proved here
-------------------------------------
``preflight/results/pace_static_small.json`` already shows this construction matching
the dynamic sliced path with ``max_abs_logit_error: 0.0``. This module therefore runs
only a cheap finiteness/stability smoke test.

Note on interleaving
--------------------
The parent is loaded on the *host* and released before workers move to the GPU, so GPU
resident bytes during a run are the workers and nothing else.

Usage
-----
    python build_worker.py --preset small --report
"""
from __future__ import annotations

import argparse
import copy
import gc
import json
import time

import torch
from transformers import AutoTokenizer, Gemma3nForCausalLM, Gemma3nForConditionalGeneration

import latency_lib as lib


def load_parent(dtype: torch.dtype, verbose: bool = True) -> Gemma3nForConditionalGeneration:
    if verbose:
        print(f"[build_worker] loading E4B parent on CPU (dtype={dtype}) ...", flush=True)
    return Gemma3nForConditionalGeneration.from_pretrained(
        lib.MODEL, revision=lib.REVISION, dtype=dtype, local_files_only=True).eval()


def extract_worker(parent, preset: str, dtype: torch.dtype, device: str = "cuda",
                   verbose: bool = True):
    """Slice ``preset``'s widths out of an already-loaded parent. Returns (worker, info)."""
    widths = lib.preset_widths(preset)
    started = time.monotonic()
    config = copy.deepcopy(parent.config.text_config)
    config.intermediate_size = list(widths)
    with torch.device("meta"):
        worker = Gemma3nForCausalLM(config).eval()

    # Slice on the host. ``contiguous()`` matters for more than tidiness: a view such as
    # ``down_proj[:, :W]`` is non-contiguous, and ``Tensor.to(device)`` preserves strides,
    # so a non-contiguous view would land non-contiguous on the GPU and silently slow the
    # FFN GEMMs -- a measurement confound. ``contiguous()`` returns the tensor itself when
    # the slice already spans the whole tensor, which is fine here: the parent is kept
    # alive until every worker has been moved to the device and is only then released, so
    # aliasing costs host memory but never correctness. An earlier version called
    # ``.clone()`` as well, which forced a full re-read of the ~16 GiB checkpoint from the
    # network filesystem for every worker and dominated startup time.
    source = parent.state_dict()
    mapped = {}
    for name, target in worker.state_dict().items():
        source_name = (("model.language_model." + name[len("model."):])
                       if name.startswith("model.") else name)
        tensor = source[source_name]
        if ".mlp.gate_proj.weight" in name or ".mlp.up_proj.weight" in name:
            tensor = tensor[:widths[int(name.split("layers.")[1].split(".")[0])]]
        elif ".mlp.down_proj.weight" in name:
            tensor = tensor[:, :widths[int(name.split("layers.")[1].split(".")[0])]]
        if tensor.shape != target.shape:
            raise AssertionError(f"shape mismatch for {name}: {tuple(tensor.shape)} vs {tuple(target.shape)}")
        mapped[name] = tensor.contiguous()
    worker.load_state_dict(mapped, strict=True, assign=True)

    # Non-persistent buffers (notably embed_scale) are absent from state_dict.
    source_buffers = dict(parent.named_buffers())
    for name, buffer in list(worker.named_buffers()):
        if buffer.device.type == "meta":
            source_name = (("model.language_model." + name[len("model."):])
                           if name.startswith("model.") else name)
            if source_name not in source_buffers:
                raise AssertionError(f"missing non-persistent buffer {name} -> {source_name}")
            module_name, attribute = name.rsplit(".", 1)
            setattr(worker.get_submodule(module_name), attribute, source_buffers[source_name])
    if any(p.device.type == "meta" for p in worker.parameters()) or \
       any(b.device.type == "meta" for b in worker.buffers()):
        raise AssertionError("worker still has meta state")
    del source, mapped

    worker = worker.to(device).eval()
    buckets = lib.param_bytes_by_bucket(worker)
    info = {"preset": preset, "widths": widths, "dtype": str(dtype),
            "device": torch.cuda.get_device_name(0),
            "load_seconds": time.monotonic() - started, "param_bytes": buckets,
            "narrow_ffn_layers": sum(1 for w in widths if w < 16384),
            "wide_ffn_layers": sum(1 for w in widths if w >= 16384)}
    if verbose:
        print(f"[build_worker] {preset}: {buckets['total'] / 1024**3:.2f} GiB weights "
              f"(ffn {buckets.get('ffn', 0) / 1024**3:.2f} GiB, "
              f"embeddings {buckets.get('embeddings', 0) / 1024**3:.2f} GiB), "
              f"narrow={info['narrow_ffn_layers']}, {info['load_seconds']:.1f}s", flush=True)
    return worker, info


def build_worker(preset: str, dtype: torch.dtype, device: str = "cuda",
                 tokenizer=None, verbose: bool = True):
    """Return ``(model, tokenizer, info)`` for a single preset."""
    parent = load_parent(dtype, verbose)
    if tokenizer is None:
        tokenizer = AutoTokenizer.from_pretrained(lib.MODEL, revision=lib.REVISION,
                                                  local_files_only=True)
    worker, info = extract_worker(parent, preset, dtype, device, verbose)
    del parent
    gc.collect()
    return worker, tokenizer, info


def build_workers(presets, dtype: torch.dtype, device: str = "cuda", verbose: bool = True):
    """Build several presets from one parent load.

    Interleaving presets within a single process is what makes the paired statistics in
    ``latency_math`` valid, and that requires every preset to be resident at once --
    roughly 11.7 / 12.7 / 13.7 GiB for small / medium / large. On a 44 GiB device that
    fits; if it does not, pass fewer presets per process (e.g. ``--presets small,large``)
    rather than serialising them, because serialising destroys the pairing.
    """
    presets = list(presets)
    parent = load_parent(dtype, verbose)
    tokenizer = AutoTokenizer.from_pretrained(lib.MODEL, revision=lib.REVISION,
                                              local_files_only=True)
    workers, infos = {}, {}
    for preset in presets:
        workers[preset], infos[preset] = extract_worker(parent, preset, dtype, device, verbose)
    del parent
    gc.collect()
    return workers, tokenizer, infos


def smoke_test(worker, tokenizer, device: str = "cuda") -> dict:
    """Cheap correctness gate: finite logits and a stable repeated forward pass."""
    ids = tokenizer("The capital of France is", return_tensors="pt")["input_ids"].to(device)
    with torch.inference_mode():
        first = worker(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
        second = worker(input_ids=ids, use_cache=False, logits_to_keep=1).logits.float()
    delta = (first - second).abs().max().item()
    if not bool(torch.isfinite(first).all()):
        raise AssertionError("non-finite logits from worker smoke test")
    return {"finite_logits": True, "repeat_max_abs_delta": delta,
            "argmax": int(first.argmax(-1).item()), "logits_shape": list(first.shape)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    lib.add_common_args(parser)
    parser.add_argument("--report", action="store_true")
    args = parser.parse_args()
    if not args.preset:
        args.preset = "small"
    print("protocol:", json.dumps(lib.prepare_runtime(args)), flush=True)
    worker, tokenizer, info = build_worker(args.preset, lib.dtype_of(args))
    lib.reset_peak_memory()
    with torch.inference_mode():
        info["smoke"] = smoke_test(worker, tokenizer)
    info["peak_after_load"] = lib.peak_memory_snapshot()
    print(json.dumps(info, indent=2), flush=True)
    print("PASS build_worker", flush=True)


if __name__ == "__main__":
    main()
