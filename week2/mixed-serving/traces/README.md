# Traces for the mixed-serving harness

Committed (a few hundred KB total) so every run is offline and reproducible. The raw
source CSVs are **not** committed: `code/fetch_trace.py` downloads them into
`traces/raw/` (git-ignored) and their sha256 travels into every derived manifest, so a
window can always be traced back to the exact bytes it came from.

## Source and licence

* **Azure LLM inference trace 2023** — `data/AzureLLMInferenceTrace_conv.csv` and
  `data/AzureLLMInferenceTrace_code.csv` in the
  [Azure Public Dataset](https://github.com/Azure/AzurePublicDataset) repository,
  schema `TIMESTAMP, ContextTokens, GeneratedTokens`. Licensed CC-BY-4.0; cite the
  accompanying paper: Patel, Choukse, Zhang, Shah, Goiri, Maleki, Bianchini,
  *Splitwise: Efficient generative LLM inference using phase splitting*, ISCA 2024.
* The Azure trace does not contain prompt text (privacy). Like the dataset's own
  replay, the harness sends a deterministic prompt of exactly the trace's token length
  and forces the trace's output length, so *sizes* are real and *content* is a stand-in.
  Content cannot change latency; `week1/latency-baselines/latency_lib.build_prompt_ids`
  is the frozen helper that provides the exactly-N-token prompt.

Measured on the copies this harness was built against (sha256 in `manifest.json`):

| File | Rows | Span | Mean rate | ctx p50 / p90 / max | gen p50 / p90 / max |
|---|---:|---:|---:|---|---|
| `AzureLLMInferenceTrace_conv.csv` | 19,366 | 3,502 s | 5.53 req/s | 1,020 / 2,734 / 14,050 | 129 / 424 / 1,000 |
| `AzureLLMInferenceTrace_code.csv` | 8,819 | 3,436 s | 2.57 req/s | 1,469 / 5,186 / 7,437 | 13 / 55 / 1,899 |

## Why these, and not the alternatives

* **Alibaba `clusterdata`** — GPU v2020/v2023 are *job/pod* scheduling traces
  (creation/deletion/scheduled times, `gpu_milli`, 1,523 nodes / 8,152 pods): no prompt
  length, no output length, no per-request LLM arrival. The 2026 GenAI (GenTD26) release
  is diffusion + LoRA serving measured as gateway QPS, queue-response-time and GPU
  utilisation series, again with no per-request token counts. Neither can express a
  prefill/decode split, which is the only thing this harness varies.
* **BurstGPT (KDD'25)** — the right fields (`Request tokens`, `Response tokens`) but
  ~50 MB per file and a mean of ~0.28 req/s. Used here as a *shape prior* for the
  synthetic burst generator (Gamma arrivals with a declared CV), not as a committed trace.
* **ShareGPT-style length distributions** — used by DistServe/Sarathi/Llumnix as
  synthetic mixes; here the length mixes come from the real windows instead, and the
  synthetic controls are lognormal fits recorded in the file itself.

## The committed set

| File | Window / generator | Purpose |
|---|---|---|
| `azure_conv_steady.json` | 180 s window whose mean rate is closest to the trace mean (989 requests, 5.50 req/s, ctx p50 1,023, gen p50 199) | representative load; the calibration reference |
| `azure_conv_burst.json` | 180 s window with the highest mean rate (1,408 requests, 7.84 req/s, ctx p50 430, gen p50 90) | the strongest real overload this day offers — note it is also a *short-prompt* period, i.e. decode-heavy overload |
| `azure_conv_mixshift.json` | 180 s window with the largest change between its halves (1,274 requests, 7.08 req/s) | the "changing request-length mix" regime |
| `azure_code_steady.json`, `azure_code_burst.json`, `azure_code_mixshift.json` | same criteria on the code trace (p50 output 12–14 tokens) | prefill-heavy negative control: ~10% decode, so the prefill lever should barely matter |
| `synth_poisson.json` | Poisson arrivals at 5.5 req/s, lognormal lengths fitted from the conv statistics | isolates mixed lengths from arrival burstiness; reproducible without the source file |
| `synth_gamma_burst.json` | Gamma arrivals (CV 2.0) with a declared 3× burst for 30 s | pushes harder than the real window, still fully reproducible from the file |
| `manifest.json` | source sha256, the declared selection criterion, window offsets, per-trace statistics | provenance for every window |

Window selection is a *declared statistic* over a sliding 180 s window with a 60 s
stride (`steady` = closest to the global mean rate; `burst` = highest rate; `mixshift`
= largest half-to-half change in mean prompt length and rate), computed by
`code/workload.py azure-windows`. Nothing is hand-picked; the criterion is recorded in
`manifest.json`, and the same rule reproduces the same windows from the same CSV bytes.

**Load is swept at run time, not by editing traces:** `--rate-scale λ` compresses
arrival times (`t → t/λ`), which preserves the window's request mix and arrival order
and only changes how fast the same work arrives. `results/costs/capacity.json` derives
the recommended λ values from measured capacity before any policy comparison.
