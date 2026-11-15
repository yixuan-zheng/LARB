# Scaled-serving code

CPU-safe package and GPU entrypoints for the week 7 scaled serving rig.

## Layout

| Path | Purpose |
|---|---|
| `larb_scaled/contract.py`, `policy.py` | Pure request contract and pressure/cut policy; CPU-tested. |
| `larb_scaled/config.py`, `datasets.py`, `workload.py` | Frozen config, normalization and trace generation. |
| `larb_scaled/stats.py`, `grading.py`, `analysis.py` | Power, extraction, per-request and paired analysis. |
| `larb_scaled/bus.py` | In-process telemetry shared by the server and controller. |
| `larb_scaled/controller.py` | vLLM scheduler/logits-processor adapter; GPU import only. |
| `larb_scaled/server.py` | Local vLLM HTTP service; GPU import only. |
| `larb_scaled/client.py`, `runner.py` | Replay client, phase planning, dry-run and execution. |
| `tools/` | Data fetch, cohort build, trace build, synthetic rehearsal, CPU checks. |
| `tests/` | `unittest` suite; no GPU or model needed. |
| `sbatch/` | Draft allocation scripts; they do not submit themselves. |

## CPU checks

```sh
PYTHONPATH=week7/scaled-serving/code python3 -m unittest discover \
  -s week7/scaled-serving/code/tests -p 'test_*.py'
PYTHONPATH=week7/scaled-serving/code python3 \
  week7/scaled-serving/code/tools/run_cpu_checks.py
```

## GPU entrypoints

```sh
PYTHONPATH=week7/scaled-serving/code python3 -m larb_scaled.runner \
  --stage p1-gates --out /path/to/run --dry-run
PYTHONPATH=week7/scaled-serving/code python3 -m larb_scaled.runner \
  --stage p2-main --out /path/to/run --dry-run
```

Remove `--dry-run` only under a reviewed Slurm allocation. The runner never submits a job.
