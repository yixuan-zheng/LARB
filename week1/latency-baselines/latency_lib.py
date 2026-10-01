"""Shared torch/CUDA scaffolding for the Week 1 FFN-width latency profile.

Scope
-----
Every scenario script in this directory measures *statically extracted* Gemma 3n
sub-models (one FFN width per process) with one request at a time and eager PyTorch
unless a scenario explicitly opts into a faster backend. Dynamic width switching and
switching cost are deliberately out of scope; the preflight package established that
side of the story separately.

What this module owns
---------------------
* run manifest: exact argv, git SHA, versions, device, clocks, protocol
* incremental crash-safe JSON records (same convention as the preflight scripts)
* the interleaved measurement sweep with warmup, L2 flush and paired sampling
* wall-clock (perf_counter) *and* CUDA-event timing, so launch overhead is separable
* clock ramp + optional clock guard, because this GPU idles at ~210 MHz SM
* analytic FLOP/byte model wiring and utilization conversion

What it does not own
--------------------
Statistical inference (see ``latency_math``) and scenario definitions (see ``s*.py``).
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import random
import subprocess
import sys
import time
import types
from pathlib import Path

import torch
import torch.nn.functional as F

import latency_math as lm

ROOT = Path(__file__).resolve().parent
RUN_OUTPUT = ROOT / "run-output"
RESULTS = ROOT / "results"
RUN_OUTPUT.mkdir(exist_ok=True)
RESULTS.mkdir(exist_ok=True)
PRESETS_PATH = ROOT.parent.parent / "preflight" / "code" / "presets.json"
MODEL = "google/gemma-3n-E4B"
REVISION = "af70430f84ea4d7ac191aaa2bd8e14d2a5e8f6ee"
DEFAULT_SEED = 6222
DTYPES = {"bfloat16": torch.bfloat16, "float32": torch.float32, "float16": torch.float16}
DTYPE_BYTES = {"bfloat16": 2, "float32": 4, "float16": 2}
#: Natural text tiled/truncated to a requested token length. Content is irrelevant
#: to latency; the token-id hash is recorded so a workload is reproducible.
PROMPT_TEXT = (
    "The history of scientific computing is a history of approximations. "
    "Early numerical analysts worked by hand, tabulating logarithms because a "
    "table lookup was faster than any alternative they could afford. When "
    "machines arrived, the tables moved into memory, and the approximations "
    "became cleverer: iterative solvers, floating point with guard digits, and "
    "finally the dense linear algebra libraries that everything we build today "
    "still rests upon. A modern transformer spends almost all of its arithmetic "
    "in matrix multiplication, which is to say in exactly the operation those "
    "libraries were designed to make cheap. What makes the current moment "
    "interesting is that the cost of moving weights has overtaken the cost of "
    "using them: for a single sequence the arithmetic intensity is so low that "
    "the machine is mostly waiting on memory, and the only way to win is to move "
    "fewer bytes. That observation is the entire motivation for studying whether "
    "a narrower feed forward network, carved out of a wider one, can serve the "
    "same request sooner. "
)


def load_presets() -> dict:
    return json.loads(PRESETS_PATH.read_text())["presets"]


def preset_widths(preset: str) -> list:
    widths = load_presets()[preset]["ffn_hidden_dims"]
    if len(widths) != 35:
        raise ValueError(f"preset {preset!r} has {len(widths)} widths, expected 35")
    return list(widths)


def all_presets() -> list:
    return list(load_presets().keys())


# --------------------------------------------------------------------------- #
# Run manifest
# --------------------------------------------------------------------------- #
def git_info() -> dict:
    def run(*args):
        try:
            return subprocess.run(args, cwd=str(ROOT), capture_output=True, text=True,
                                  timeout=10, check=False).stdout.strip()
        except Exception:
            return ""
    sha = run("git", "rev-parse", "HEAD")
    status = run("git", "status", "--porcelain")
    return {"sha": sha or None, "dirty": bool(status),
            "dirty_files": status.splitlines()[:20]}


def versions() -> dict:
    import transformers
    info = {"python": sys.version.split()[0], "torch": torch.__version__,
            "transformers": transformers.__version__,
            "cuda": torch.version.cuda, "cudnn": torch.backends.cudnn.version()}
    try:
        info["driver"] = subprocess.run(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10, check=False).stdout.strip().splitlines()
    except Exception:
        info["driver"] = None
    return info


def device_info() -> dict:
    props = torch.cuda.get_device_properties(0)
    return {"name": props.name, "compute_capability": f"{props.major}.{props.minor}",
            "sm_count": props.multi_processor_count, "total_memory_bytes": props.total_memory}


def clocks_snapshot() -> dict:
    """Live SM/mem clock + power + utilization. This GPU idles at ~210 MHz SM, so a
    measurement taken before the clocks ramp is meaningless without recording this."""
    query = "clocks.sm,clocks.mem,power.draw,utilization.gpu"
    try:
        out = subprocess.run(["nvidia-smi", f"--query-gpu={query}", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, check=False).stdout.strip()
        sm, mem, power, util = [float(x) for x in out.split(",")]
        return {"sm_mhz": sm, "mem_mhz": mem, "power_w": power, "util_pct": util}
    except Exception as exc:
        return {"error": str(exc)}


def peaks_for(device_name: str) -> dict:
    for key, value in lm.DEFAULT_PEAKS.items():
        if key.lower() in device_name.lower():
            return dict(value, source=f"table:{key}")
    return {"bf16_tflops": None, "dram_gbps": None, "l2_bytes": None, "source": "unknown"}


def arch_spec_from_config(config, model=None) -> lm.ArchSpec:
    """Read the *actual* checkpoint shape rather than trusting hardcoded constants.

    ``tie_word_embeddings`` deserves special care: it is absent from this checkpoint's
    config JSON, so ``getattr`` falls through to ``PretrainedConfig``'s default of True,
    which wrongly drops the output projection from the byte model. S7 measured the
    resulting 1.00 GiB (exactly one ``vocab_size x hidden_size`` matrix) shortfall in both
    large and small. When a model is supplied the flag is therefore read off the live
    module -- the only source that cannot disagree with reality.
    """
    if model is not None:
        tied = not any(name.endswith("lm_head.weight")
                       for name, _ in model.named_parameters())
    else:
        tied = bool(getattr(config, "tie_word_embeddings", False))
    return lm.ArchSpec(
        hidden_size=int(config.hidden_size),
        num_layers=int(config.num_hidden_layers),
        num_attention_heads=int(config.num_attention_heads),
        num_key_value_heads=int(config.num_key_value_heads),
        head_dim=int(getattr(config, "head_dim", config.hidden_size // config.num_attention_heads)),
        num_kv_shared_layers=int(getattr(config, "num_kv_shared_layers", 0) or 0),
        laurel_rank=int(getattr(config, "laurel_rank", 0) or 0),
        altup_num_inputs=int(getattr(config, "altup_num_inputs", 0) or 0),
        hidden_size_per_layer_input=int(getattr(config, "hidden_size_per_layer_input", 0) or 0),
        vocab_size=int(config.vocab_size),
        vocab_size_per_layer_input=int(getattr(config, "vocab_size_per_layer_input", 0) or 0),
        sliding_window=int(getattr(config, "sliding_window", 0) or 0),
        layer_types=tuple(getattr(config, "layer_types", ())),
        widths=tuple(int(w) for w in config.intermediate_size),
        tied_word_embeddings=tied,
    )


# --------------------------------------------------------------------------- #
# Workload construction
# --------------------------------------------------------------------------- #
def build_prompt_ids(tokenizer, length: int, offset: int = 0) -> tuple:
    """A deterministic, exactly ``length``-token input batch padded by tiling real text.

    Returns ``(ids, sha256_of_ids)`` so every workload in a record is identifiable.
    """
    if length < 1:
        raise ValueError("length must be >= 1")
    base = tokenizer(PROMPT_TEXT, return_tensors="pt", add_special_tokens=False)["input_ids"][0]
    if base.numel() == 0:
        raise ValueError("tokenizer produced no tokens for PROMPT_TEXT")
    if offset:
        base = torch.roll(base, -int(offset))
    reps = (length + base.numel() - 1) // base.numel()
    ids = base.repeat(reps)[:length].unsqueeze(0)
    digest = hashlib.sha256(ids.cpu().numpy().tobytes()).hexdigest()
    return ids, digest


def next_token_id(tokenizer, offset: int = 0) -> torch.Tensor:
    """A real continuation token from the tokenizer vocabulary, not a magic constant.

    The preflight pilot used a hardcoded id (``[[17]]``) for its cache comparisons; a
    real token keeps the workload representative and reproducible.
    """
    ids = tokenizer(" Paris", add_special_tokens=False, return_tensors="pt")["input_ids"]
    if ids.shape[1] < 1:
        ids = tokenizer(" the", add_special_tokens=False, return_tensors="pt")["input_ids"]
    idx = int(offset) % ids.shape[1]
    return ids[:, idx:idx + 1]


# --------------------------------------------------------------------------- #
# Timing primitives
# --------------------------------------------------------------------------- #
class Timer:
    """Records wall-clock and device time for the *same* call.

    The two differ by exactly the host-side dispatch cost, which the preflight pilot
    identified as the dominant term (~46 ms of a ~55 ms step). Reporting the gap is
    therefore the point, not an implementation detail, and it is exposed as
    ``alpha_ms`` by every scenario.

    Events are allocated once and reused so the timed region contains no allocator
    traffic. ``synchronize`` before ``t0`` guarantees the GPU is idle when the clock
    starts, so the wall figure reflects this call alone.
    """

    def __init__(self, pool: int = 2):
        self._pool = [(torch.cuda.Event(enable_timing=True), torch.cuda.Event(enable_timing=True))
                      for _ in range(pool)]
        self._cursor = 0

    def time(self, fn):
        start, end = self._pool[self._cursor % len(self._pool)]
        self._cursor += 1
        torch.cuda.synchronize()
        t0 = time.perf_counter()
        start.record()
        out = fn()
        end.record()
        torch.cuda.synchronize()
        wall_ms = 1000.0 * (time.perf_counter() - t0)
        return out, wall_ms, start.elapsed_time(end)


class L2Flusher:
    """Evicts L2 between measured iterations by rewriting a scratch buffer.

    The L40S has 96 MB of L2 and the largest single FFN weight matrix is ~67 MB, so a
    warm L2 could otherwise flatter a measurement. Flushing is *conservative*: it also
    removes reuse a real serving loop would enjoy. Both configurations are therefore
    reported (``--no-flush-l2`` for the warm case) rather than only one.
    """

    def __init__(self, megabytes: float = 512.0, enabled: bool = True, device: str = "cuda"):
        self.enabled = bool(enabled)
        self.bytes = int(megabytes * 1024 * 1024)
        self.buffer = (torch.empty(self.bytes, dtype=torch.uint8, device=device)
                       if self.enabled and self.bytes > 0 else None)

    def flush(self) -> None:
        if self.buffer is not None:
            self.buffer.fill_(1)

    def describe(self) -> dict:
        return {"enabled": self.enabled, "bytes": self.bytes, "megabytes": self.bytes / 1024**2}


def clock_ramp(seconds: float = 2.0, size: int = 4096, device: str = "cuda") -> dict:
    """Drive the SM clock up before measuring.

    Observed idle state on this node: ~210 MHz SM / ~405 MHz memory at ~35 W. Timing a
    ~55 ms workload before the ramp completes would measure the governor, not the model.
    """
    if seconds <= 0:
        return {"skipped": True}
    a = torch.randn(size, size, device=device, dtype=torch.bfloat16)
    b = torch.randn(size, size, device=device, dtype=torch.bfloat16)
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        for _ in range(4):
            torch.mm(a, b)
        torch.cuda.synchronize()
    elapsed = time.monotonic() - started
    del a, b
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    return {"seconds": elapsed, "matrix": size}


def wait_for_sm_clock(min_mhz: float, timeout: float = 30.0, poll: float = 1.0) -> dict:
    """Best-effort clock guard. Shared nodes cannot be locked, so we detect and record."""
    if min_mhz <= 0:
        return {"skipped": True}
    started = time.monotonic()
    last = None
    while time.monotonic() - started < timeout:
        last = clocks_snapshot()
        if last.get("sm_mhz", 0.0) >= min_mhz:
            return {"ok": True, "clocks": last, "waited_s": round(time.monotonic() - started, 3)}
        time.sleep(poll)
    return {"ok": False, "clocks": last, "waited_s": round(time.monotonic() - started, 3),
            "min_mhz": min_mhz}


# --------------------------------------------------------------------------- #
# Memory accounting
# --------------------------------------------------------------------------- #
def _bucket_of(name: str) -> str:
    if "embed_tokens_per_layer" in name:
        return "embeddings_per_layer"
    if "embed_tokens" in name:
        return "embeddings"
    if ".mlp." in name:
        return "ffn"
    if ".self_attn." in name:
        return "attention"
    if ".altup." in name:
        return "altup"
    if ".laurel." in name:
        return "laurel"
    if "per_layer_input_gate" in name or "per_layer_projection" in name or "per_layer_model" in name:
        return "per_layer_input"
    if "norm" in name:
        return "norms"
    return "other"


def param_bytes_by_bucket(model) -> dict:
    """Exact resident weight bytes per component, measured off the live module.

    Ground truth for the memory side of the profile: the analytic model in
    ``latency_math`` predicts these, and S7 reports the delta between the two.
    """
    buckets = {}
    for name, parameter in model.named_parameters():
        size = parameter.numel() * parameter.element_size()
        buckets[_bucket_of(name)] = buckets.get(_bucket_of(name), 0) + size
    buckets["total"] = sum(buckets.values())
    return buckets


def reset_peak_memory() -> None:
    torch.cuda.synchronize()
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()


def peak_memory_snapshot() -> dict:
    return {"peak_allocated_bytes": torch.cuda.max_memory_allocated(),
            "peak_reserved_bytes": torch.cuda.max_memory_reserved(),
            "current_allocated_bytes": torch.cuda.memory_allocated()}


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def output_path(scenario: str, args) -> Path:
    if getattr(args, "out", None):
        return Path(args.out)
    preset = args.preset if getattr(args, "preset", None) else "all"
    return RUN_OUTPUT / f"{scenario}__{preset}__{getattr(args, 'tag', 'local')}.json"


def _json_fallback(value):
    print(f"[latency_lib] WARNING: coercing {type(value).__name__} to str in a record",
          file=sys.stderr, flush=True)
    return str(value)


class RunRecord:
    """Incremental, crash-safe JSON record, following the preflight convention.

    Every measurement is flushed to disk as it lands, so a preemption or OOM leaves a
    usable partial artifact; ``completed`` distinguishes a finished run from a
    truncated one without needing the log.
    """

    def __init__(self, scenario: str, args, extra_manifest: dict | None = None):
        self.path = output_path(scenario, args)
        self.data = {
            "scenario": scenario,
            "started_utc": utc_now(),
            "manifest": extra_manifest or {},
            "protocol": {},
            "samples": [],
            "summary": {},
            "comparisons": {},
            "completed": False,
        }

    def set_manifest(self, **values) -> None:
        self.data["manifest"].update(values)
        self.save()

    def set_protocol(self, **values) -> None:
        self.data["protocol"].update(values)
        self.save()

    def add_sample(self, row: dict) -> None:
        self.data["samples"].append(row)
        self.save()

    def set_summary(self, key: str, value) -> None:
        self.data["summary"][key] = value
        self.save()

    def set_comparison(self, key: str, value) -> None:
        self.data["comparisons"][key] = value
        self.save()

    def set_extra(self, key: str, value) -> None:
        self.data[key] = value
        self.save()

    def save(self) -> None:
        # ``_fallback`` keeps a long GPU run alive if a stray non-JSON value slips into
        # a record, but it warns loudly: silent coercion would be silent data loss.
        self.path.write_text(json.dumps(self.data, indent=2, default=_json_fallback) + "\n")

    def complete(self) -> None:
        self.data["completed"] = True
        self.data["finished_utc"] = utc_now()
        self.save()


# --------------------------------------------------------------------------- #
# Measurement sweep
# --------------------------------------------------------------------------- #
class Harness:
    """Round-robin interleaved sweep with warmup, L2 flush and paired sampling.

    Interleaving is the single most important change from the pilot: measuring all of
    Large and then all of Small lets clock/thermal drift masquerade as an effect. Here
    each configuration contributes exactly one sample per round, so the paired
    statistics in ``latency_math.paired_stats`` are valid by construction.

    ``prepare`` runs *outside* the timed region (it is where the prefill lives), which
    is what lets a decode step be measured at an exactly constant context length.
    """

    def __init__(self, args, device: str = "cuda", shuffle: bool = True):
        self.args = args
        self.device = device
        self.timer = Timer()
        self.shuffle = bool(shuffle)
        self.rng = random.Random(int(getattr(args, "seed", DEFAULT_SEED)))
        self.flusher = L2Flusher(getattr(args, "flush_mb", 512.0),
                                 getattr(args, "flush_l2", True), device)

    def flush(self) -> None:
        self.flusher.flush()

    def sweep(self, configs, prepare, step, warmup: int, reps: int, record=None,
              progress: bool = True) -> dict:
        samples = {cfg["key"]: [] for cfg in configs}
        for _ in range(max(0, warmup)):
            for cfg in configs:
                step(cfg, prepare(cfg))
        for rep in range(reps):
            order = list(configs)
            # Shuffling each round removes position bias: a fixed order lets whichever
            # config always runs first inherit a small systematic advantage (S0 measured
            # ~1% before this was added).
            if self.shuffle:
                self.rng.shuffle(order)
            for cfg in order:
                state = prepare(cfg)
                self.flush()
                _, wall_ms, gpu_ms = self.timer.time(lambda c=cfg, s=state: step(c, s))
                row = {"key": cfg["key"], "rep": rep, "wall_ms": wall_ms, "gpu_ms": gpu_ms,
                       "alpha_ms": wall_ms - gpu_ms, "order_index": order.index(cfg)}
                samples[cfg["key"]].append(row)
                if record is not None:
                    record.add_sample({**cfg, **row})
            if progress and (rep + 1) % max(1, reps // 10) == 0:
                print(f"    rep {rep + 1}/{reps}", flush=True)
        return samples


#: Metrics summarized for every configuration. ``wall_ms`` is what a caller feels,
#: ``gpu_ms`` is device time, and their difference is the host dispatch cost.
SUMMARY_METRICS = ("wall_ms", "gpu_ms", "alpha_ms")


def summarize_samples(samples: dict, metric: str = None) -> dict:
    """Per-configuration distribution summaries, nested as ``{key: {metric: stats}}``.

    Nesting by metric matters: an earlier flat version returned statistics for a single
    metric while every scenario indexed them per metric, which failed only at the first
    post-sweep access and cost a full model load to discover.
    """
    metrics = (metric,) if metric else SUMMARY_METRICS
    return {key: {m: lm.summarize([row[m] for row in rows]) for m in metrics}
            for key, rows in samples.items()}


def compare_pairs(samples: dict, large_key: str, small_key: str, metric: str = "wall_ms",
                  seed: int = DEFAULT_SEED, resamples: int = 10000,
                  effect_threshold: float = 0.02) -> dict:
    left = [row[metric] for row in samples[large_key]]
    right = [row[metric] for row in samples[small_key]]
    return {"metric": metric, "large_key": large_key, "small_key": small_key,
            **lm.paired_stats(left, right, resamples=resamples, seed=seed,
                              effect_threshold=effect_threshold)}


# --------------------------------------------------------------------------- #
# CLI / runtime setup
# --------------------------------------------------------------------------- #
def add_common_args(parser: argparse.ArgumentParser, default_reps: int = 40,
                    default_warmup: int = 10) -> argparse.ArgumentParser:
    parser.add_argument("--presets", default="small,medium,large",
                        help="comma-separated presets, or 'all'")
    parser.add_argument("--preset", default=None, help="this process measures exactly one preset")
    parser.add_argument("--reps", type=int, default=default_reps)
    parser.add_argument("--warmup", type=int, default=default_warmup)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--dtype", choices=sorted(DTYPES), default="bfloat16")
    parser.add_argument("--threads", type=int, default=4)
    parser.add_argument("--flush-l2", dest="flush_l2", action="store_true", default=True)
    parser.add_argument("--no-flush-l2", dest="flush_l2", action="store_false")
    parser.add_argument("--flush-mb", type=float, default=512.0)
    parser.add_argument("--clock-ramp-s", type=float, default=2.0)
    parser.add_argument("--min-sm-clock-mhz", type=float, default=0.0,
                        help="0 disables the guard; 2000 is the recommended value here")
    parser.add_argument("--strict-clock", action="store_true")
    parser.add_argument("--peak-tflops", type=float, default=None)
    parser.add_argument("--peak-gbps", type=float, default=None)
    parser.add_argument("--tag", default="local")
    parser.add_argument("--out", default=None)
    parser.add_argument("--estimate-only", action="store_true")
    return parser


def resolve_peaks(args, device_name: str) -> dict:
    peaks = peaks_for(device_name)
    if getattr(args, "peak_tflops", None):
        peaks["bf16_tflops"], peaks["source"] = args.peak_tflops, "cli:--peak-tflops"
    if getattr(args, "peak_gbps", None):
        peaks["dram_gbps"], peaks["source"] = args.peak_gbps, "cli:--peak-gbps"
    return peaks


def prepare_runtime(args) -> dict:
    """Deterministic, documented runtime state. Returns the flags for the manifest."""
    if not torch.cuda.is_available():
        raise SystemExit("CUDA is required: this suite times GPU forward passes.")
    torch.set_num_threads(int(args.threads))
    torch.manual_seed(int(args.seed))
    # Fixed algorithm selection keeps kernel choice identical across presets, which
    # would otherwise differ with shape width and add a confound to the comparison.
    torch.backends.cudnn.benchmark = False
    torch.backends.cuda.matmul.allow_tf32 = False
    os.environ.setdefault("PYTORCH_ALLOC_CONF", "expandable_segments:True")
    return {"threads": torch.get_num_threads(), "seed": int(args.seed),
            "shuffled_sweep_order": True,
            "cudnn_benchmark": torch.backends.cudnn.benchmark,
            "allow_tf32": torch.backends.cuda.matmul.allow_tf32,
            
            "torch_alloc_conf": (os.environ.get("PYTORCH_ALLOC_CONF") or os.environ.get("PYTORCH_CUDA_ALLOC_CONF")),
            "inference_mode": True, "greedy": True}


def base_manifest(args, scenario: str) -> dict:
    return {"scenario": scenario, "argv": sys.argv, "cwd": str(Path.cwd()),
            "git": git_info(), "versions": versions(), "device": device_info(),
            "model": MODEL, "revision": REVISION, "local_files_only": True,
            "dtype": args.dtype, "dtype_bytes": DTYPE_BYTES[args.dtype],
            "preset_used": args.preset,
            "preset_widths": preset_widths(args.preset) if args.preset else None,
            "presets_source": str(PRESETS_PATH)}


def selected_presets(args) -> list:
    if args.preset:
        return [args.preset]
    if args.presets == "all":
        return all_presets()
    return [name.strip() for name in args.presets.split(",") if name.strip()]


def dtype_of(args) -> torch.dtype:
    return DTYPES[args.dtype]


def estimate_wall_time(configs: int, reps: int, warmup: int, ms_per_iter: float) -> dict:
    total = (reps + warmup) * configs
    return {"iterations": total, "assumed_ms_per_iter": ms_per_iter,
            "estimated_seconds": total * ms_per_iter / 1000.0}


# --------------------------------------------------------------------------- #
# Derived utilization metrics
# --------------------------------------------------------------------------- #
def derived_metrics(spec, widths, param_bytes_total: int, peaks: dict, ms: float,
                    batch: int, q_len: int, ctx_len: int, kv_bytes: int = 0,
                    causal: bool = True) -> dict:
    """Turn one measured duration into bandwidth and MFU utilization.

    ``bytes_moved`` is deliberately a *lower bound*: every parameter must be read at
    least once per forward pass, so ``param_bytes_total / time`` is the most
    optimistic bandwidth figure available without a hardware counter. Beating it is
    impossible; falling far short of it means the step is not weight-bound at all,
    which is exactly the situation the preflight pilot found itself in.
    """
    seconds = (ms or 0.0) / 1000.0
    flops = lm.flops_per_step(spec, widths, batch, q_len, ctx_len, causal)
    bytes_moved = int(param_bytes_total) + int(kv_bytes)
    out = {"flops": flops["total_flops"], "ffn_flops": flops["ffn_flops"],
           "ffn_flop_share": flops["ffn_share"], "bytes_moved_lower_bound": bytes_moved}
    if seconds > 0:
        out["achieved_bw_gbps"] = bytes_moved / seconds / 1e9
        out["flops_per_second"] = flops["total_flops"] / seconds
        if peaks.get("dram_gbps"):
            out["bw_utilization"] = out["achieved_bw_gbps"] / peaks["dram_gbps"]
        if peaks.get("bf16_tflops"):
            out["mfu"] = out["flops_per_second"] / (peaks["bf16_tflops"] * 1e12)
    return out


# --------------------------------------------------------------------------- #
# VRAM budgeting
# --------------------------------------------------------------------------- #
def activation_bytes_estimate(spec, widths, batch: int, q_len: int, dtype_bytes: int) -> int:
    """Order-of-magnitude peak activation footprint for one prefill/decode pass.

    Dominated by the hidden states (replicated across attention and residual paths) and
    by the widest FFN intermediate. Deliberately an over-estimate: it is used to *skip*
    configurations that would OOM, and a crash in the middle of a multi-hour sweep is
    far more expensive than refusing to run one grid point.
    """
    hidden = batch * q_len * spec.hidden_size * dtype_bytes
    widest = max(widths) if widths else 0
    ffn = batch * q_len * widest * dtype_bytes * 2
    return int(hidden * 4 + ffn * 2)


def free_vram_bytes() -> int:
    free, _ = torch.cuda.mem_get_info()
    return int(free)


def vram_budget_check(spec, widths, batch: int, q_len: int, dtype_bytes: int,
                      fraction: float = 0.6) -> dict:
    """Would this configuration fit? Returns a dict with a ``skipped_reason`` if not."""
    estimate = activation_bytes_estimate(spec, widths, batch, q_len, dtype_bytes)
    free = free_vram_bytes()
    ok = estimate <= fraction * free
    out = {"estimated_activation_bytes": estimate, "free_bytes_at_check": free,
           "budget_fraction": fraction, "ok": bool(ok)}
    if not ok:
        out["skipped_reason"] = (f"activation estimate {estimate / 1024**3:.2f} GiB exceeds "
                                 f"{fraction:.0%} of {free / 1024**3:.2f} GiB free VRAM")
    return out
