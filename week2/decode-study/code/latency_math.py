"""Pure-stdlib statistics and analytic cost model for the Week 1 latency profile.

Importable without torch or numpy, so the math can be unit tested on a login node
(see ``test_flop_model.py``). ``latency_lib.py`` adds the torch/CUDA side and reuses
everything here.

Scope
-----
1. Robust summary statistics and *paired* comparison statistics for latency samples
   collected by the timing harness in ``latency_lib.py``.
2. An analytic FLOP/byte cost model for Gemma 3n text layers, used to convert
   wall-clock measurements into MFU and achieved-bandwidth utilization.

Non-claims
----------
The cost model is a *dense* operator count. Gemma 3n's activation sparsity
(``_gaussian_topk``) is implemented as a dense mean/std/relu chain, so it removes no
FLOPs and is credited with none here. AltUp / Laurel / per-layer-input elementwise
traffic is counted in bytes only, because those ops are bandwidth bound, not FLOP
bound. Treat the FLOP figure as a lower bound on arithmetic and the byte figure as
the quantity a decode step must physically move.
"""
from __future__ import annotations

import dataclasses
import math
import random
from dataclasses import dataclass
from typing import Iterable, Sequence


# --------------------------------------------------------------------------- #
# Summary statistics
# --------------------------------------------------------------------------- #
def quantile(sorted_values: Sequence[float], q: float) -> float:
    """Linear-interpolation quantile of an already sorted sequence; q in [0, 1]."""
    if not sorted_values:
        raise ValueError("empty sample")
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1.0 - frac) + sorted_values[hi] * frac)


def summarize(samples: Iterable[float]) -> dict:
    """Distribution summary reported for every latency metric.

    Median and p90 are the headline numbers: latency distributions are long-tailed,
    so a mean alone would hide the tail that a serving system actually feels.
    """
    values = sorted(float(v) for v in samples)
    n = len(values)
    if n == 0:
        raise ValueError("empty sample")
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / (n - 1) if n > 1 else 0.0
    std = math.sqrt(var)
    p10, p25, p50, p75, p90 = (quantile(values, q) for q in (0.10, 0.25, 0.50, 0.75, 0.90))
    return {
        "n": n, "min": values[0], "p10": p10, "p25": p25, "median": p50,
        "mean": mean, "p75": p75, "p90": p90, "max": values[-1],
        "std": std, "iqr": p75 - p25, "cv": (std / mean) if mean else 0.0,
    }


def bootstrap_ratio_ci(large: Sequence[float], small: Sequence[float],
                       resamples: int = 10000, seed: int = 6222,
                       alpha: float = 0.05) -> tuple:
    """Paired bootstrap CI for mean(small)/mean(large).

    Resampling *indices* (not the two samples independently) preserves the pairing
    that the interleaved measurement order creates, and therefore cancels slow
    clock/thermal drift instead of absorbing it into the interval.
    """
    if len(large) != len(small) or not large:
        raise ValueError("paired bootstrap needs equal-length non-empty samples")
    rng = random.Random(seed)
    n = len(large)
    ratios = []
    for _ in range(resamples):
        idx = [rng.randrange(n) for _ in range(n)]
        a = sum(large[i] for i in idx)
        b = sum(small[i] for i in idx)
        if a > 0.0:
            ratios.append(b / a)
    ratios.sort()
    return quantile(ratios, alpha / 2.0), quantile(ratios, 1.0 - alpha / 2.0)


def paired_stats(large: Sequence[float], small: Sequence[float],
                 resamples: int = 10000, seed: int = 6222,
                 effect_threshold: float = 0.02) -> dict:
    """Paired Large-vs-Small comparison with a pre-registered claim rule.

    A difference is only called ``appreciable`` when BOTH hold:
      * the bootstrap CI of the paired mean ratio excludes 1.0, and
      * the median paired delta exceeds ``effect_threshold`` of the Large median.
    Anything else is reported as within noise, which is the honest default at this
    effect size.
    """
    large, small = [float(v) for v in large], [float(v) for v in small]
    if len(large) != len(small) or not large:
        raise ValueError("paired_stats needs equal-length non-empty samples")
    n = len(large)
    diffs = [s - l for l, s in zip(large, small)]
    mean_diff = sum(diffs) / n
    sd = math.sqrt(sum((d - mean_diff) ** 2 for d in diffs) / (n - 1)) if n > 1 else 0.0
    # Minimum detectable paired mean difference at 95% confidence for this n.
    mdd = 1.96 * sd / math.sqrt(n) if n > 1 else float("inf")
    s_large, s_small = summarize(large), summarize(small)
    ratio = s_small["mean"] / s_large["mean"] if s_large["mean"] else float("inf")
    lo, hi = bootstrap_ratio_ci(large, small, resamples, seed)
    ci_excludes_one = (lo > 1.0) or (hi < 1.0)
    delta_median = s_small["median"] - s_large["median"]
    rel = abs(delta_median) / s_large["median"] if s_large["median"] else 0.0
    appreciable = bool(ci_excludes_one and rel > effect_threshold)
    return {
        "n": n, "large": s_large, "small": s_small,
        "median_delta_ms": delta_median,
        "median_delta_pct": 100.0 * delta_median / s_large["median"] if s_large["median"] else 0.0,
        "mean_ratio": ratio, "ratio_lo": lo, "ratio_hi": hi,
        "speedup": (1.0 / ratio) if ratio else 0.0,
        "paired_sd_ms": sd, "mdd_ms": mdd,
        "mdd_pct": 100.0 * mdd / s_large["median"] if s_large["median"] else 0.0,
        "ci_excludes_one": ci_excludes_one,
        "effect_threshold": effect_threshold,
        "appreciable": appreciable,
        "verdict": ("appreciable" if appreciable else "within_noise"),
    }


# --------------------------------------------------------------------------- #
# Least squares (stdlib only) -- used to fit the latency model in analyze_latency
# --------------------------------------------------------------------------- #
def _solve(matrix: list, rhs: list) -> list:
    """Gaussian elimination with partial pivoting; small dense systems only."""
    n = len(rhs)
    a = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(a[r][col]))
        if abs(a[pivot][col]) < 1e-18:
            raise ValueError("singular normal-equation matrix")
        a[col], a[pivot] = a[pivot], a[col]
        inv = 1.0 / a[col][col]
        for r in range(col + 1, n):
            factor = a[r][col] * inv
            if factor:
                for c in range(col, n + 1):
                    a[r][c] -= factor * a[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = a[r][n] - sum(a[r][c] * x[c] for c in range(r + 1, n))
        x[r] = acc / a[r][r]
    return x


def linear_fit(features: Sequence[Sequence[float]], targets: Sequence[float]) -> dict:
    """Least-squares fit of ``targets`` on ``features`` (caller supplies intercept)."""
    if not features or len(features) != len(targets):
        raise ValueError("features/targets mismatch")
    n_rows, n_cols = len(features), len(features[0])
    if n_rows < n_cols:
        raise ValueError("underdetermined: fewer observations than coefficients")
    xtx = [[sum(features[r][i] * features[r][j] for r in range(n_rows)) for j in range(n_cols)]
           for i in range(n_cols)]
    xty = [sum(features[r][i] * targets[r] for r in range(n_rows)) for i in range(n_cols)]
    coef = _solve(xtx, xty)
    preds = [sum(features[r][i] * coef[i] for i in range(n_cols)) for r in range(n_rows)]
    mean_t = sum(targets) / n_rows
    ss_res = sum((t - p) ** 2 for t, p in zip(targets, preds))
    ss_tot = sum((t - mean_t) ** 2 for t in targets)
    return {"coef": coef, "r2": (1.0 - ss_res / ss_tot) if ss_tot else 0.0,
            "ss_res": ss_res, "ss_tot": ss_tot,
            "predict": lambda values, _c=coef: sum(c * v for c, v in zip(_c, values))}


# --------------------------------------------------------------------------- #
# Analytic cost model for Gemma 3n text layers
# --------------------------------------------------------------------------- #
#: Dense-peak figures for known devices. Overridable from the CLI so a run on
#: different hardware never silently reports MFU against the wrong roof.
DEFAULT_PEAKS = {
    "NVIDIA L40S": {"bf16_tflops": 362.05, "dram_gbps": 864.0, "l2_bytes": 96 * 1024**2},
    "NVIDIA A100-SXM4-80GB": {"bf16_tflops": 312.0, "dram_gbps": 2039.0, "l2_bytes": 40 * 1024**2},
    "NVIDIA H100 PCIe": {"bf16_tflops": 756.0, "dram_gbps": 2000.0, "l2_bytes": 50 * 1024**2},
}


@dataclass(frozen=True)
class ArchSpec:
    """Static text-side shape of Gemma 3n, independent of FFN width."""

    hidden_size: int = 2048
    num_layers: int = 35
    num_attention_heads: int = 8
    num_key_value_heads: int = 2
    head_dim: int = 256
    num_kv_shared_layers: int = 15
    laurel_rank: int = 64
    altup_num_inputs: int = 4
    hidden_size_per_layer_input: int = 256
    vocab_size: int = 262400
    vocab_size_per_layer_input: int = 262144
    sliding_window: int = 512
    layer_types: tuple = ()
    widths: tuple = ()
    tied_word_embeddings: bool = False

    @staticmethod
    def e4b_text() -> "ArchSpec":
        """Values read from the pinned ``google/gemma-3n-E4B`` text_config.

        Layer i is ``full_attention`` when ``i % 5 == 4`` (indices 4, 9, 14, 19,
        24, 29, 34), exactly as in the checkpoint's ``layer_types``.
        """
        return ArchSpec(
            widths=(16384,) * 35,
            layer_types=tuple(
                "full_attention" if i % 5 == 4 else "sliding_attention" for i in range(35)))

    def __post_init__(self) -> None:
        """Catch a silently empty or mis-sized width list before it becomes a zero.

        An empty ``widths`` makes ``ffn_flops`` return 0 without error, which would quietly
        poison every MFU figure derived from it; validate instead.
        """
        if self.layer_types and len(self.layer_types) != self.num_layers:
            raise ValueError(f"layer_types has {len(self.layer_types)} entries, "
                             f"expected {self.num_layers}")
        if self.widths and len(self.widths) != self.num_layers:
            raise ValueError(f"widths has {len(self.widths)} entries, expected {self.num_layers}")

    def with_widths(self, widths: Sequence[int]) -> "ArchSpec":
        """A copy of this spec with per-layer FFN widths (``small``/``medium``/``large``)."""
        if len(widths) != self.num_layers:
            raise ValueError(f"expected {self.num_layers} widths, got {len(widths)}")
        return dataclasses.replace(self, widths=tuple(int(w) for w in widths))


def full_intermediate_size(spec: ArchSpec) -> list:
    """The unsliced FFN width for every layer (16384 for E4B)."""
    return [16384] * spec.num_layers


def first_kv_shared_layer(spec: ArchSpec) -> int:
    return spec.num_layers - spec.num_kv_shared_layers


def kv_owning_layers(spec: ArchSpec) -> list:
    """``(layer_idx, store_full_length)`` for layers that keep their own KV cache.

    Mirrors ``Gemma3nTextAttention``: layers at or beyond ``first_kv_shared_layer``
    own no projections and no cache entries, and among the owners only the last
    layer of each attention type stores full-length KV; the rest are windowed.
    """
    first = first_kv_shared_layer(spec)
    previous = list(spec.layer_types[:first])
    owners = []
    for idx in range(first):
        layer_type = spec.layer_types[idx]
        last_of_type = len(previous) - 1 - previous[::-1].index(layer_type)
        owners.append((idx, idx == last_of_type))
    return owners


def ffn_flops(spec: ArchSpec, widths: Sequence[int], m_tokens: int) -> float:
    """gate + up + down, dense: 6 * m * H * W per layer."""
    return 6.0 * m_tokens * spec.hidden_size * float(sum(widths))


def attn_proj_flops(spec: ArchSpec, m_tokens: int) -> float:
    """q/o for all layers; k/v only for layers that own them."""
    q_out = spec.num_attention_heads * spec.head_dim
    kv_out = spec.num_key_value_heads * spec.head_dim
    per_own = 2.0 * m_tokens * spec.hidden_size * (2 * q_out + 2 * kv_out)
    per_shared = 2.0 * m_tokens * spec.hidden_size * (2 * q_out)
    n_own = len(kv_owning_layers(spec))
    return n_own * per_own + (spec.num_layers - n_own) * per_shared


def attn_core_flops(spec: ArchSpec, batch: int, q_len: int, ctx_len: int,
                    causal: bool = True) -> float:
    """Scores + weighted-value matmuls, honouring the sliding window and causality."""
    if q_len < 1 or ctx_len < q_len:
        raise ValueError("need 1 <= q_len <= ctx_len")
    first_query = ctx_len - q_len
    attended_keys = 0.0
    for layer_type in spec.layer_types:
        window = min(ctx_len, spec.sliding_window) if layer_type == "sliding_attention" else ctx_len
        if causal:
            attended_keys += sum(min(first_query + i + 1, window) for i in range(q_len))
        else:
            attended_keys += float(q_len * window)
    return 4.0 * spec.num_attention_heads * spec.head_dim * batch * attended_keys


def flops_per_step(spec: ArchSpec, widths: Sequence[int], batch: int, q_len: int,
                   ctx_len: int, causal: bool = True) -> dict:
    """FLOP breakdown for one forward pass (prefill has q_len == ctx_len)."""
    m = batch * q_len
    ffn = ffn_flops(spec, widths, m)
    proj = attn_proj_flops(spec, m)
    core = attn_core_flops(spec, batch, q_len, ctx_len, causal)
    total = ffn + proj + core
    return {"ffn_flops": ffn, "attn_proj_flops": proj, "attn_core_flops": core,
            "total_flops": total, "m_tokens": m,
            "ffn_share": (ffn / total) if total else 0.0}


def ffn_weight_bytes(spec: ArchSpec, widths: Sequence[int], dtype_bytes: int) -> int:
    return 3 * spec.hidden_size * sum(int(w) for w in widths) * dtype_bytes


def attn_weight_bytes(spec: ArchSpec, dtype_bytes: int) -> int:
    q_out = spec.num_attention_heads * spec.head_dim
    kv_out = spec.num_key_value_heads * spec.head_dim
    own = 2.0 * spec.hidden_size * (q_out + 2 * kv_out)
    shared = 2.0 * spec.hidden_size * q_out
    n_own = len(kv_owning_layers(spec))
    return int((n_own * own + (spec.num_layers - n_own) * shared) * dtype_bytes)


def embedding_bytes(spec: ArchSpec, dtype_bytes: int) -> int:
    """Token table plus the per-layer token table (the width-independent bulk)."""
    tokens = spec.vocab_size * spec.hidden_size
    per_layer = spec.vocab_size_per_layer_input * spec.num_layers * spec.hidden_size_per_layer_input
    return int((tokens + per_layer) * dtype_bytes)


def other_linear_bytes(spec: ArchSpec, dtype_bytes: int) -> int:
    """Laurel, AltUp coefficients/routers, and the per-layer input gate/projection."""
    laurel = 2 * spec.hidden_size * spec.laurel_rank
    altup = spec.altup_num_inputs + spec.altup_num_inputs**2 + spec.hidden_size * spec.altup_num_inputs
    gate = spec.hidden_size * spec.hidden_size_per_layer_input
    proj = spec.hidden_size_per_layer_input * spec.hidden_size
    return int(spec.num_layers * (laurel + altup + gate + proj) * dtype_bytes)


def lm_head_bytes(spec: ArchSpec, dtype_bytes: int) -> int:
    """Untied output projection.

    Gemma 3n does *not* tie the LM head to the token embedding, so this is a full
    ``vocab_size x hidden_size`` matrix (1.00 GiB in bf16). It was missing from the first
    version of this model; S7's analytic-vs-measured delta flagged the 8.5% shortfall.
    """
    if spec.tied_word_embeddings:
        return 0
    return int(spec.vocab_size * spec.hidden_size * dtype_bytes)


def weight_bytes(spec: ArchSpec, widths: Sequence[int], dtype_bytes: int) -> dict:
    parts = {
        "ffn": ffn_weight_bytes(spec, widths, dtype_bytes),
        "attention": attn_weight_bytes(spec, dtype_bytes),
        "embeddings": embedding_bytes(spec, dtype_bytes),
        "other_linear": other_linear_bytes(spec, dtype_bytes),
        "lm_head": lm_head_bytes(spec, dtype_bytes),
    }
    parts["total"] = sum(parts.values())
    return parts


def kv_resident_bytes(spec: ArchSpec, ctx_len: int, batch: int, dtype_bytes: int) -> int:
    """KV bytes actually held for ``batch`` sequences at ``ctx_len`` context.

    Upper bound when ``store_full_length`` is set; windowed layers are capped.
    S7 records the real numbers off the live cache object, so this analytic figure
    is a cross-check rather than the source of truth.
    """
    per_token_per_layer = 2 * spec.num_key_value_heads * spec.head_dim * dtype_bytes
    tokens = 0.0
    for _, store_full in kv_owning_layers(spec):
        tokens += ctx_len if store_full else min(ctx_len, spec.sliding_window)
    return int(tokens * per_token_per_layer * batch)


def mfu(flops: float, seconds: float, peak_tflops: float) -> float:
    return flops / (seconds * peak_tflops * 1e12) if seconds > 0 else 0.0


def bw_utilization(bytes_moved: float, seconds: float, peak_gbps: float) -> float:
    return bytes_moved / (seconds * peak_gbps * 1e9) if seconds > 0 else 0.0
