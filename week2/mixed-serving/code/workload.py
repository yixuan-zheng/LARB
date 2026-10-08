"""Trace ingest, window selection and synthetic arrival generation (stdlib only).

Why this module exists
----------------------
The harness needs a workload that (a) mixes prefill and decode, (b) can be
driven into genuine overload, (c) is reproducible from a small committed
artifact, and (d) needs no GPU to prepare.  All four come from one decision:
replay a **window of a real production LLM-serving trace** instead of a
synthetic cohort.

Source: the Azure LLM inference traces shipped inside the Azure public dataset
repository (CC-BY), ``data/AzureLLMInferenceTrace_conv.csv`` and
``data/AzureLLMInferenceTrace_code.csv``.  Schema ``TIMESTAMP, ContextTokens,
GeneratedTokens``.  Measured on the copy this harness was built against:

* ``conv``: 19,366 requests over 3,502 s (mean 5.53 req/s, peak minute ~8.4 req/s);
  context tokens mean 1,155 / p50 1,020 / p90 2,734 / p99 4,142 / max 14,050;
  generated tokens mean 211 / p50 129 / p90 424 / p99 601 / max 1,000; 719 KB.
* ``code``: 8,819 requests over 3,436 s (2.57 req/s); context p50 1,469 / p99 7,436;
  generated p50 13 / p99 249; 320 KB.

The files are downloaded once by ``fetch_trace.py`` into ``traces/raw/`` (git
ignored) and normalized here into small canonical JSON windows that *are*
committed.  Nothing in the harness touches the network at run time, and the
sha256 of every raw file is carried into every derived manifest.

Why this trace and not the others
---------------------------------
* Alibaba ``clusterdata`` GPU traces (v2020/v2023) are *job/pod* scheduling traces
  (creation/deletion/scheduled times, ``gpu_milli``): no prompt length, no output
  length, no per-request LLM arrival.  The 2026 GenAI (GenTD26) release is
  diffusion + LoRA serving with gateway QPS / queue / GPU-utilisation series,
  again without per-request token counts.  Neither can express a prefill/decode
  split.
* BurstGPT (KDD'25) has the right fields (``Request tokens``, ``Response tokens``)
  but ships ~50 MB per file and averages 0.28 req/s; it is used here as a
  burstiness *shape prior* for the synthetic generator, not as a committed trace.
* The Azure windows are the smallest artifacts that carry a real burst structure
  and a real prefill/decode mix, which is what a single-GPU run budget can replay.
"""
from __future__ import annotations

import csv
import datetime as _dt
import hashlib
import json
import math
import random
from dataclasses import dataclass, field
from pathlib import Path

SCHEMA_VERSION = 1
#: Window geometry.  180 s keeps a window inside one sbatch hour at lambda <= 1.5
#: while still carrying hundreds of requests at the observed 2.5-8 req/s.
DEFAULT_WINDOW_S = 180.0
DEFAULT_STRIDE_S = 60.0
#: Synthetic generator cap (the max generated/context length is declared, not sampled).
DEFAULT_LENGTH_CAP = 4096
#: Request prefix used when the source rows carry no ids.
ID_PREFIX = "req"


def _percentile(sorted_values, q):
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return float(sorted_values[0])
    pos = q * (len(sorted_values) - 1)
    lo, hi = int(math.floor(pos)), int(math.ceil(pos))
    if lo == hi:
        return float(sorted_values[lo])
    frac = pos - lo
    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)


# --------------------------------------------------------------------------- #
# Raw trace ingest
# --------------------------------------------------------------------------- #
def _parse_timestamp(value):
    """A datetime, or seconds.  Azure writes '2023-11-16 18:15:46.6805900'."""
    text = str(value).strip()
    try:
        return float(text)
    except ValueError:
        pass
    head, _, frac = text.partition(".")
    stamp = _dt.datetime.strptime(head, "%Y-%m-%d %H:%M:%S")
    micros = int(round(float("0." + frac) * 1e6)) if frac else 0
    return stamp + _dt.timedelta(microseconds=micros)


def read_azure_csv(path) -> dict:
    """Read one Azure LLM inference CSV into parallel arrays + provenance."""
    path = Path(path)
    with path.open(newline="") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"empty trace {path}")
    header = {k.strip().lower(): k for k in rows[0]}
    for required in ("timestamp", "contexttokens", "generatedtokens"):
        if required not in header:
            raise ValueError(f"{path}: expected TIMESTAMP/ContextTokens/GeneratedTokens, "
                             f"got {sorted(rows[0])}")
    stamps = [_parse_timestamp(r[header["timestamp"]]) for r in rows]
    base = min(stamps)
    if isinstance(base, _dt.datetime):
        t_s = [(s - base).total_seconds() for s in stamps]
    else:
        t_s = [float(s) - float(base) for s in stamps]
    out = {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "n_rows": len(rows),
        "t_s": [round(v, 6) for v in t_s],
        "prompt_tokens": [int(r[header["contexttokens"]]) for r in rows],
        "output_tokens": [int(r[header["generatedtokens"]]) for r in rows],
    }
    out["span_s"] = max(out["t_s"]) if out["t_s"] else 0.0
    return out


def trace_stats(t_s, prompt_tokens, output_tokens) -> dict:
    ps, gs = sorted(prompt_tokens), sorted(output_tokens)
    span = (max(t_s) - min(t_s)) if t_s else 0.0
    total_req_tokens = sum(ps) + sum(gs)
    return {
        "requests": len(t_s),
        "span_s": span,
        "mean_rps": (len(t_s) / span) if span else 0.0,
        "prompt_tokens": {"mean": sum(ps) / len(ps), "p50": _percentile(ps, 0.5),
                          "p90": _percentile(ps, 0.9), "p99": _percentile(ps, 0.99),
                          "max": ps[-1]},
        "output_tokens": {"mean": sum(gs) / len(gs), "p50": _percentile(gs, 0.5),
                          "p90": _percentile(gs, 0.9), "p99": _percentile(gs, 0.99),
                          "max": gs[-1]},
        "prefill_token_share": (sum(ps) / total_req_tokens) if total_req_tokens else 0.0,
    }



# --------------------------------------------------------------------------- #
# Window selection (deterministic; the criterion is written into the manifest)
# --------------------------------------------------------------------------- #
def window_slice(raw: dict, start_s: float, window_s: float) -> dict:
    """Rows with start <= t < start + window, rebased so the window starts at 0."""
    keep = [i for i, t in enumerate(raw["t_s"]) if start_s <= t < start_s + window_s]
    return {
        "t_s": [raw["t_s"][i] - start_s for i in keep],
        "prompt_tokens": [raw["prompt_tokens"][i] for i in keep],
        "output_tokens": [raw["output_tokens"][i] for i in keep],
    }


def _half_stats(win: dict) -> tuple:
    """(mean prompt tokens, rate) for each half of a window."""
    mid = len(win["t_s"]) // 2
    out = []
    for lo, hi in ((0, mid), (mid, len(win["t_s"]))):
        chunk = win["prompt_tokens"][lo:hi]
        times = win["t_s"][lo:hi]
        mean_ctx = (sum(chunk) / len(chunk)) if chunk else 0.0
        rate = (len(times) / (max(times) - min(times))) if len(times) > 1 else 0.0
        out.append((mean_ctx, rate))
    return out[0], out[1]


def select_windows(raw: dict, window_s: float = DEFAULT_WINDOW_S,
                   stride_s: float = DEFAULT_STRIDE_S, top_k: int = 1) -> dict:
    """Rank sliding windows under three *declared* criteria.

    * ``steady`` - mean rate closest to the global mean rate (representative load).
    * ``burst``  - highest mean rate (the strongest real overload this trace offers).
    * ``mixshift`` - largest change between the two halves of the window, scored as
      ``|mean_ctx_2 - mean_ctx_1| / mean_ctx_all + |rate_2 - rate_1| / rate_all``
      (both terms dimensionless): the length mix and the load both move.

    Nothing here is hand-picked; the criterion, offsets and window statistics all
    go into ``traces/manifest.json``.
    """
    global_stats = trace_stats(raw["t_s"], raw["prompt_tokens"], raw["output_tokens"])
    global_rps = global_stats["mean_rps"]
    global_ctx = global_stats["prompt_tokens"]["mean"]
    latest = max(0.0, raw["span_s"] - window_s)
    offsets, off = [], 0.0
    while off <= latest + 1e-9:
        offsets.append(round(off, 6))
        off += stride_s
    if not offsets or offsets[-1] < latest - 1e-9:
        offsets.append(round(latest, 6))
    candidates = []
    for off in offsets:
        win = window_slice(raw, off, window_s)
        if len(win["t_s"]) < 5:
            continue
        stats = trace_stats(win["t_s"], win["prompt_tokens"], win["output_tokens"])
        (ctx1, rate1), (ctx2, rate2) = _half_stats(win)
        shift = (abs(ctx2 - ctx1) / global_ctx if global_ctx else 0.0) + \
                (abs(rate2 - rate1) / global_rps if global_rps else 0.0)
        candidates.append({"start_s": off, "window_s": window_s, "stats": stats,
                           "rate_score": abs(stats["mean_rps"] - global_rps),
                           "mixshift_score": shift, "slice": win})
    if not candidates:
        raise ValueError("no window long enough in this trace")
    picks = {}
    for criterion, key in (("steady", lambda c: (c["rate_score"], -c["stats"]["requests"])),
                           ("burst", lambda c: (-c["stats"]["mean_rps"], c["start_s"])),
                           ("mixshift", lambda c: (-c["mixshift_score"], c["start_s"]))):
        picks[criterion] = sorted(candidates, key=key)[:top_k]
    return {"global": global_stats, "candidates": candidates, "picks": picks}

    return float(sorted_values[lo] * (1 - frac) + sorted_values[hi] * frac)



# --------------------------------------------------------------------------- #
# Canonical trace artifact
# --------------------------------------------------------------------------- #
def canonical_trace(trace_id: str, t_s, prompt_tokens, output_tokens, *, source: dict,
                    generator: dict, seed: int = 6222, notes=None) -> dict:
    """Build the canonical trace dict (the only shape the loop understands)."""
    order = sorted(range(len(t_s)), key=lambda i: (t_s[i], i))
    requests = [{"request_id": f"{ID_PREFIX}{i:06d}",
                 "arrival_s": round(float(t_s[i]), 6),
                 "prompt_tokens": int(prompt_tokens[i]),
                 "output_tokens": int(output_tokens[i])} for i in order]
    base = requests[0]["arrival_s"] if requests else 0.0
    for r in requests:  # rebase so the first arrival is exactly 0.0
        r["arrival_s"] = round(r["arrival_s"] - base, 6)
    return {
        "schema_version": SCHEMA_VERSION,
        "trace_id": trace_id,
        "seed": int(seed),
        "source": dict(source),
        "generator": dict(generator),
        "notes": list(notes or []),
        "stats": trace_stats([r["arrival_s"] for r in requests],
                             [r["prompt_tokens"] for r in requests],
                             [r["output_tokens"] for r in requests]),
        "requests": requests,
    }


@dataclass
class Trace:
    """A loaded canonical trace plus its provenance."""

    trace_id: str
    requests: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.requests = sorted(self.requests, key=lambda r: (r["arrival_s"], r["request_id"]))

    @property
    def span_s(self) -> float:
        return self.requests[-1]["arrival_s"] if self.requests else 0.0

    def with_rate_scale(self, rate_scale: float) -> "Trace":
        """Time-compress arrivals: ``t -> t / rate_scale`` (lambda > 1 = more load).

        This is the load ladder: it preserves the window's request mix and arrival
        order exactly and only changes how fast the same work arrives, so a run at
        another lambda is the same workload at a different pressure.  Documented
        because it also compresses the burst's absolute duration.
        """
        if rate_scale <= 0:
            raise ValueError("rate_scale must be > 0")
        meta = dict(self.meta)
        meta["rate_scale"] = float(rate_scale)
        return Trace(self.trace_id, [dict(r, arrival_s=r["arrival_s"] / float(rate_scale))
                                     for r in self.requests], meta)

    def with_limit(self, limit: int) -> "Trace":
        if limit and limit < len(self.requests):
            meta = dict(self.meta)
            meta["limited_to"] = int(limit)
            return Trace(self.trace_id, [dict(r) for r in self.requests[:limit]], meta)
        return self

    def summary(self) -> dict:
        return trace_stats([r["arrival_s"] for r in self.requests],
                           [r["prompt_tokens"] for r in self.requests],
                           [r["output_tokens"] for r in self.requests])

    def to_dict(self) -> dict:
        return {"schema_version": SCHEMA_VERSION, "trace_id": self.trace_id, **self.meta,
                "stats": self.summary(), "requests": self.requests}


def write_trace(trace: dict, path) -> str:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trace, indent=1) + "\n")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_trace(path, rate_scale: float = 1.0, limit: int = 0) -> Trace:
    raw = json.loads(Path(path).read_text())
    if raw.get("schema_version") != SCHEMA_VERSION:
        raise ValueError(f"{path}: unsupported schema_version {raw.get('schema_version')!r}")
    requests = raw["requests"]
    for r in requests:
        for key in ("arrival_s", "prompt_tokens", "output_tokens"):
            if key not in r:
                raise ValueError(f"{path}: request missing {key!r}")
        if int(r["prompt_tokens"]) < 1:
            raise ValueError(f"{path}: request {r['request_id']} has an empty prompt")
    meta = {k: v for k, v in raw.items() if k not in ("requests", "stats", "schema_version")}
    trace = Trace(raw["trace_id"], requests, meta)
    if rate_scale != 1.0:
        trace = trace.with_rate_scale(rate_scale)
    return trace.with_limit(limit)



# --------------------------------------------------------------------------- #
# Synthetic arrivals (Poisson and Gamma, per Llumnix's burstiness methodology)
# --------------------------------------------------------------------------- #
def lognormal_from_median_p90(median: float, p90: float) -> dict:
    """Parametrize a lognormal by median and p90, so a fit is self-describing."""
    median = max(1.0, float(median))
    p90 = max(median * 1.0001, float(p90))
    sigma = (math.log(p90) - math.log(median)) / 1.2815515655446004
    return {"median": median, "p90": p90, "mu": math.log(median), "sigma": sigma}


def _sample_lognormal(rng, params, lo: int, hi: int) -> int:
    return int(min(max(round(rng.lognormvariate(params["mu"], params["sigma"])), lo), hi))


def generate_synthetic(trace_id: str, *, rate_rps: float, duration_s: float = 180.0,
                       kind: str = "poisson", cv: float = 1.0, seed: int = 6222,
                       prompt_params: dict, output_params: dict,
                       prompt_range=(16, DEFAULT_LENGTH_CAP),
                       output_range=(1, 1024), bursts=None,
                       source_stats=None) -> dict:
    """Self-contained synthetic trace: only the declared parameters are needed.

    ``kind='poisson'`` gives exponential inter-arrivals (CV = 1); ``kind='gamma'``
    gives Gamma inter-arrivals at the requested coefficient of variation
    (shape = 1/CV^2, scale = 1/rate/CV^2), which is how Llumnix sweeps burstiness.
    ``bursts`` optionally superimposes declared load multipliers, so a stress case
    beyond the real window stays reproducible from the file alone.
    """
    rng = random.Random(int(seed))
    if kind not in ("poisson", "gamma"):
        raise ValueError("kind must be 'poisson' or 'gamma'")
    shape = 1.0 if kind == "poisson" else 1.0 / max(1e-6, float(cv)) ** 2
    scale = (1.0 / float(rate_rps)) / shape
    bursts = list(bursts or [])

    def multiplier(t: float) -> float:
        mult = 1.0
        for b in bursts:
            if float(b["start_s"]) <= t < float(b["start_s"]) + float(b["duration_s"]):
                mult *= float(b["multiplier"])
        return mult

    t, guard = 0.0, 0
    t_s, prompt_tokens, output_tokens = [], [], []
    while t < duration_s and guard < 2_000_000:
        guard += 1
        t += rng.gammavariate(shape, scale) / max(1e-9, multiplier(t))
        if t >= duration_s:
            break
        t_s.append(t)
        prompt_tokens.append(_sample_lognormal(rng, prompt_params, *prompt_range))
        output_tokens.append(_sample_lognormal(rng, output_params, *output_range))
    return canonical_trace(
        trace_id, t_s, prompt_tokens, output_tokens,
        source={"kind": "synthetic", "url": None, "sha256": None,
                "params_fitted_from": source_stats},
        generator={"kind": kind, "rate_rps": float(rate_rps), "duration_s": float(duration_s),
                   "cv": float(cv), "shape": shape, "scale": scale,
                   "prompt_lognormal": prompt_params, "output_lognormal": output_params,
                   "prompt_range": list(prompt_range), "output_range": list(output_range),
                   "bursts": bursts, "lengths_sampled_independently": True},
        seed=seed,
        notes=["Synthetic control: arrivals only. The length distributions are lognormal "
               "fits, not the raw Azure rows, so this file is reproducible without the "
               "source CSV."])


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
AZURE_URLS = {
    "conv": "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/"
            "AzureLLMInferenceTrace_conv.csv",
    "code": "https://raw.githubusercontent.com/Azure/AzurePublicDataset/master/data/"
            "AzureLLMInferenceTrace_code.csv",
}


def _synthetic_set(raw, rate) -> list:
    """Two synthetic controls, fitted from the real trace's own length statistics."""
    stats = trace_stats(raw["t_s"], raw["prompt_tokens"], raw["output_tokens"]) if raw else None
    p_med = stats["prompt_tokens"]["p50"] if stats else 1020.0
    p_p90 = stats["prompt_tokens"]["p90"] if stats else 2734.0
    g_med = stats["output_tokens"]["p50"] if stats else 129.0
    g_p90 = stats["output_tokens"]["p90"] if stats else 424.0
    prompt_params = lognormal_from_median_p90(p_med, p_p90)
    output_params = lognormal_from_median_p90(g_med, g_p90)
    fit_note = {"prompt_median": p_med, "prompt_p90": p_p90,
                "output_median": g_med, "output_p90": g_p90,
                "source_sha256": raw["sha256"] if raw else None}
    return [
        generate_synthetic("synth_poisson", rate_rps=rate, duration_s=180.0, kind="poisson",
                           cv=1.0, seed=6222, prompt_params=prompt_params,
                           output_params=output_params, source_stats=fit_note),
        generate_synthetic("synth_gamma_burst", rate_rps=rate, duration_s=180.0, kind="gamma",
                           cv=2.0, seed=6222, prompt_params=prompt_params,
                           output_params=output_params, source_stats=fit_note,
                           bursts=[{"start_s": 60.0, "duration_s": 30.0, "multiplier": 3.0}]),
    ]


def build_azure_windows(conv_csv, code_csv, out_dir, window_s, stride_s,
                        synthetic_rate=5.5) -> dict:
    """Write the committed trace set plus ``manifest.json``; return the manifest."""
    out_dir = Path(out_dir)
    manifest = {"window_s": window_s, "stride_s": stride_s, "sources": {}, "traces": {}}
    for tag, csv_path in (("conv", conv_csv), ("code", code_csv)):
        if not csv_path:
            continue
        raw = read_azure_csv(csv_path)
        sel = select_windows(raw, window_s, stride_s)
        manifest["sources"][tag] = {
            "path": raw["path"], "sha256": raw["sha256"], "n_rows": raw["n_rows"],
            "span_s": raw["span_s"], "global_stats": sel["global"]}
        for criterion, picked in sel["picks"].items():
            win = picked[0]
            trace_id = f"azure_{tag}_{criterion}"
            doc = canonical_trace(
                trace_id, win["slice"]["t_s"], win["slice"]["prompt_tokens"],
                win["slice"]["output_tokens"],
                source={"kind": f"azure_llm_2023_{tag}", "url": AZURE_URLS[tag],
                        "sha256": raw["sha256"], "window_start_s": win["start_s"],
                        "window_len_s": window_s},
                generator={"kind": "measured_trace",
                           "selection_criterion": criterion,
                           "rate_score": win["rate_score"],
                           "mixshift_score": win["mixshift_score"]},
                seed=6222,
                notes=[f"Window selected by the declared '{criterion}' criterion over a "
                       f"{window_s:.0f} s sliding window with a {stride_s:.0f} s stride; "
                       f"offsets and statistics are in manifest.json."])
            path = out_dir / f"{trace_id}.json"
            digest = write_trace(doc, path)
            manifest["traces"][trace_id] = {
                "file": path.name, "sha256": digest, "requests": doc["stats"]["requests"],
                "mean_rps": doc["stats"]["mean_rps"], "criterion": criterion,
                "window_start_s": win["start_s"], "source": doc["source"]["kind"],
                "stats": doc["stats"]}
            print(f"[workload] {path.name:<32} n={doc['stats']['requests']:<5} "
                  f"rps={doc['stats']['mean_rps']:6.2f} "
                  f"ctx_p50={doc['stats']['prompt_tokens']['p50']:7.0f} "
                  f"gen_p50={doc['stats']['output_tokens']['p50']:6.0f} ({criterion})")
    raw_conv = read_azure_csv(conv_csv) if conv_csv else None
    for doc in _synthetic_set(raw_conv, synthetic_rate):
        path = out_dir / f"{doc['trace_id']}.json"
        digest = write_trace(doc, path)
        manifest["traces"][doc["trace_id"]] = {
            "file": path.name, "sha256": digest, "requests": doc["stats"]["requests"],
            "mean_rps": doc["stats"]["mean_rps"], "criterion": "synthetic",
            "source": "synthetic", "stats": doc["stats"]}
        print(f"[workload] {path.name:<32} n={doc['stats']['requests']:<5} "
              f"rps={doc['stats']['mean_rps']:6.2f} (synthetic)")
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return manifest


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)

    win = sub.add_parser("azure-windows",
                         help="normalize Azure windows and write the synthetic controls")
    win.add_argument("--conv", default="traces/raw/AzureLLMInferenceTrace_conv.csv")
    win.add_argument("--code", default="traces/raw/AzureLLMInferenceTrace_code.csv")
    win.add_argument("--out", default="traces")
    win.add_argument("--window", type=float, default=DEFAULT_WINDOW_S)
    win.add_argument("--stride", type=float, default=DEFAULT_STRIDE_S)
    win.add_argument("--synthetic-rate", type=float, default=5.5)

    summ = sub.add_parser("summary", help="print one trace's statistics")
    summ.add_argument("--trace", required=True)
    summ.add_argument("--rate-scale", type=float, default=1.0)

    args = parser.parse_args()
    if args.command == "azure-windows":
        conv = args.conv if Path(args.conv).exists() else None
        code = args.code if Path(args.code).exists() else None
        if conv is None:
            print(f"[workload] WARNING: {args.conv} missing; run fetch_trace.py first")
        if code is None:
            print(f"[workload] WARNING: {args.code} missing")
        build_azure_windows(conv, code, args.out, args.window, args.stride,
                            args.synthetic_rate)
    else:
        trace = load_trace(args.trace, rate_scale=args.rate_scale)
        print(json.dumps({"trace_id": trace.trace_id, "rate_scale": args.rate_scale,
                          **trace.summary()}, indent=1))
        print(json.dumps({"generator": trace.meta.get("generator"),
                          "source": trace.meta.get("source")}, indent=1))


if __name__ == "__main__":
    main()


