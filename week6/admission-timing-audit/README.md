# Week 6: where live-budget savings stop becoming goodput

**Finding:** live control reduced queue delay and token use, but correctness changes cancelled its deadline gains. Completed request slots were reused promptly. The next proposed test separates budget choice at HTTP arrival from reconsideration at actual engine entry.

## Start here

- [CPU audit report](REPORT.md): evidence across 244 requests, paired accounting, timing/slot analysis and prediction limitations.
- [Decision and stopping conditions](DECISION.md): one admission-timing hypothesis and a proposed three-arm falsification experiment. **Not implemented or submitted.**
- [Completed follow-up results](FOLLOWUP-RESULTS.md): both matched blocks, strict caps/extraction review and all four policies.
- [Related-work comparison](RELATED-WORK.md): methods, evaluation differences and reproduction limits.

| Policy | Overall correct | Correct on time | Mean latency | Output tokens |
|---|---:|---:|---:|---:|
| Fixed 4K | 10/40 | 8/40 | 111.9s | 219,813 |
| Fixed 8K | 17/40 | 12/40 | 218.1s | 368,033 |
| HTTP arrival-only | 16/40 | 11/40 | 197.0s | 343,840 |
| Full live | 13/40 | 11/40 | 140.7s | 287,346 |

Full live saves 16.4% output tokens and 28.5% mean latency versus arrival-only, but loses three correct answers overall. Its three correct-on-time gains are cancelled by three losses. The repeated burst deadline gain comes from one question under two seeds; this is not broad generalization evidence.

## Why the next hypothesis changed

Every measured burst has a request whose HTTP budget is 8K but is reduced at worker entry before generating any tokens. The latest two such requests waited about 24s and 31s after the initial decision. We should distinguish that second admission decision from interrupting established reasoning. The proposed experiment compares HTTP-only, one worker-entry reconsideration, and full live, without introducing a quality predictor.

The initial deadline-prediction candidate did not pass its sensitivity gate. More complex rescue logic is not the default next action. Review the [decision](DECISION.md) before implementation or GPU allocation.

## How this builds on Week 5

The [Builder report](../../week5/builder/REPORT.md) established live mechanics on an easier cohort. The [Explorer](../../week5/explorer/targeting.py) supplied a deadline-rescue shadow rule; corrected FIFO lane reuse is retained as an approximation. The [quality follow-up](../../week5/pressure-followup/README.md) established budget headroom and negative lightweight routing results. This package adds the completed arrival-only ablation and CPU diagnosis on the harder workload.

## Reproduce the compact evidence

From the repository root, using only the Python standard library:

```sh
python3 -B week6/admission-timing-audit/analysis/reproduce.py
```

This checks published aggregates, paired gains/losses, cut timelines, release counts, prediction-error summaries and public file hashes from compact derived records. It does **not** re-run generation, decode raw tokens, re-grade raw answers, reconstruct every scheduler event or refit timing profiles.

Full CPU reconstruction code is in [analysis/raw-audit/](analysis/raw-audit/). It requires the original private result collections, which are intentionally excluded. With those already present, reproduce into a new directory:

```sh
AUDIT_TEMP=$(mktemp -d /tmp/larb-week6-audit.XXXXXX)
python3 -B week6/admission-timing-audit/analysis/raw-audit/extract.py --out "$AUDIT_TEMP/derived"
python3 -B week6/admission-timing-audit/analysis/raw-audit/predict.py --derived "$AUDIT_TEMP/derived"
python3 -B week6/admission-timing-audit/analysis/raw-audit/aggregate.py --derived "$AUDIT_TEMP/derived"
python3 -B week6/admission-timing-audit/analysis/raw-audit/paths.py --derived "$AUDIT_TEMP/derived"
python3 -B week6/admission-timing-audit/analysis/raw-audit/verify.py --derived "$AUDIT_TEMP/derived"
```

## Scope and privacy

Essential reports, CPU code and derived results only. All 244 records are represented, including 232 measured responses and 12 probes; the primary current comparison has 40 matched cases across 12 unique development questions. Caps and failures remain in their denominators. Related queues and repeated questions are dependent; no naive per-response significance claim or counterfactual hybrid accuracy is published.

Raw prompts/generations/token arrays, original cluster logs, credentials, login names, private paths and large per-second sampled states remain outside this handoff. Input hashes are preserved in [source-provenance.json](evidence/source-provenance.json). [VERIFICATION.json](VERIFICATION.json) separates the original full audit from checks reproducible using this public package.
