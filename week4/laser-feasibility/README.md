# 6B: LASER baseline feasibility

The [assessment](REPORT.md) is the starting point. It recommends a small integration/mechanics step before a large 6C campaign. The current controller and 5C evidence are unchanged; this folder contains CPU work, source inspection, and synthetic-tokenizer checks only.

| File | Purpose |
| --- | --- |
| [REPORT.md](REPORT.md) | Feasibility, adaptations, fairness risks, and the remaining decision |
| [contract.json](contract.json) | Draft probe, confidence, budget, runtime, cost and calibration choices; not a frozen GPU plan |
| [reference.py](reference.py) | Pure CPU policy, confidence, lifecycle and cost boundaries |
| [test_reference.py](test_reference.py) | Boundary, identity, cancellation and accounting cases |
| [validation.json](validation.json) | Test results, unchanged controller hashes and scoped CPU timing |
| [sources.json](sources.json) | Primary-source URLs, pins and hashes; no vendored model scripts |
| [source-audit.json](source-audit.json) | Default-load saturation, scoped upstream helper checks, and tag/installation agreement |
| [runtime-audit.json](runtime-audit.json) | Installed vLLM source hashes and AST method inventory; no engine constructed |
| [encoding-audit.json](encoding-audit.json) | Cached pinned tokenizer on synthetic strings only |

## Reproduce the CPU checks

Python 3.10 or newer, no model libraries needed:

```bash
python3 -B week4/laser-feasibility/check.py
```

This runs 21 tests, checks the controller against the existing candidate lock, and updates `validation.json`. The timing is a local scalar microbenchmark, not end-to-end serving overhead. It reads no problem/answer records and does not initialize an engine.

For the source audit, download the URLs from `sources.json` to a temporary directory, preserving their dictionary-key filenames, then:

```bash
python3 -B week4/laser-feasibility/inspect_sources.py --source-dir /path/to/temporary/sources
```

For example, the downloads can use verified HTTPS without running any retrieved scripts:

```bash
python3 - <<'PY'
import json, subprocess, tempfile
from pathlib import Path
manifest = json.loads(Path('week4/laser-feasibility/sources.json').read_text())
with tempfile.TemporaryDirectory() as tmp:
    for name, item in manifest['files'].items():
        subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error',
                        '--max-time', '60', item['url'], '-o', str(Path(tmp) / name)], check=True)
    subprocess.run(['python3', '-B', 'week4/laser-feasibility/inspect_sources.py',
                    '--source-dir', tmp], check=True)
PY
```

The inspector requires the recorded bytes before extracting one function AST from the pinned DEER file. It supplies a scalar math stub instead of importing Torch/vLLM. Source hashes are strict: changed HTML serialization can require reviewing the source snapshot rather than silently updating a pin. The public helper observations are compatibility tests, not a model result.

In the prepared vLLM environment, installed-source and optional offline-tokenizer checks can be reproduced with:

```bash
python -B week4/laser-feasibility/runtime_probe.py --out /path/to/cpu-audit \
  --model-path "$BUDGET_MODEL_PATH"
```

`BUDGET_MODEL_PATH` is local environment configuration pointing to the pinned Qwen3 snapshot. This reads package metadata/source and a tokenizer; it never constructs vLLM or loads model weights. The successful check used the prepared runtime cache. An initial attempt used the default cache location and found no snapshot; it performed no inference, and was corrected to the existing prepared cache without downloading weights.

## Picking up from here

The reference is ready to guide integration, not to launch inference. Token-aligned marker parsing, probe output extraction, role-aware serving orchestration, load/queue semantics and complete cost transport still need implementation and a small exposed-only mechanics gate. A native fork would need additional runtime engineering; a serial replay prototype is a disclosed adaptation with paid recomputation.

The [shared handoff](../HANDOFF.md) records the recommended next action. No jobs are active from this work and no 6C compute plan has been authorized. Future notes can link the chosen backend, passed mechanics checks, remaining limitations and the proposed matched comparison, so the next person can distinguish CPU evidence from serving evidence.
