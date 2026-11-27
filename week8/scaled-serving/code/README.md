# Week 8 code

This directory imports the frozen Week 7 rig and adds the Week 8 qualification,
preview, calibration and serving-policy machinery. The Week 7 code is read-only;
its hashes are checked by `larb_week8.config.verify_week7_source_lock()`.

| path | purpose |
|---|---|
| `larb_week8/pilot.py` | P2C quality-first burst pilot: trace build, phase plan, GPU runner, safe grading, paired analysis and fail-fast decision |
| `larb_week8/prefill.py` | P3C prefilled-cohort cut stress: six arms, 4k/6k cut targets, cohort/burst/tail analysis and combined A + corrected live6k analysis |
| `sitecustomize.py` | Engine-process `LARB_CUT_TARGET` propagation for the 6k cut; inert unless the variable is set |
| `larb_week8/preview.py`, `calibrate.py`, `decision.py` | P2A/P2B preview, calibration and decision records (historical; P2B is closed) |
| `larb_week8/candidate.py`, `traces.py`, `runner.py` | AIME pool/trace plumbing and the Week 8 server/runner wrapper |
| `larb_week8/audit.py` | Safe normalised grading and the P1 slope audit |
| `tools/candidate_phase.py` | Historical P2A/P2B stage CLI (`build`, `plan`, `calibration`, `live`, `freeze`, `main`) |
| `tools/analyze_slope_history.py` | Reproduces the family-level 4k→8k slope analysis |
| `tests/test_pilot.py` | CPU tests for the P2C trace shape, phase plan, paired arithmetic and fail-fast decisions |
| `tests/test_prefill.py` | CPU tests for the P3C prefilled trace, six-arm plan, cut targets and decision arithmetic |
| `tests/test_pipeline.py` | CPU tests for preview, calibration, live check, candidate freeze and runner boundaries |

## Commands

Set `ROOT`, `WEEK8`, `PY` and `APY` for your environment; `PY` runs serving code
and `APY` runs analysis code (the latter needs `math_verify`). The frozen Week 7
code must be present at `$ROOT/week7/scaled-serving/code`.

```sh
export ROOT=/path/to/LARB
export WEEK8=$ROOT/week8/scaled-serving
export PYTHONPATH=$WEEK8/code:$ROOT/week7/scaled-serving/code
export PY=${PY:-python3}
export APY=${APY:-python3}

# CPU checks
bash $WEEK8/code/tools/run_cpu_all.sh
$APY -m unittest discover -s $WEEK8/code/tests -p 'test_*.py'

# P2C burst pilot
$APY -m larb_week8.pilot --stage build --which both
$APY -m larb_week8.pilot --stage plan --which both
$PY  -m larb_week8.pilot --stage run --which a --out $WEEK8/results/p2c/pilot
$APY -m larb_week8.pilot --stage analyse --out $WEEK8/results/p2c/pilot
$PY  -m larb_week8.pilot --stage run --which b --out $WEEK8/results/p2c/pilot
$APY -m larb_week8.pilot --stage analyse --out $WEEK8/results/p2c/pilot

# P3C prefilled-cohort cut stress
$APY -m larb_week8.prefill --stage build
$APY -m larb_week8.prefill --stage plan
$PY  -m larb_week8.prefill --stage run --out $WEEK8/results/p3c/prefill
$APY -m larb_week8.prefill --stage analyse --out $WEEK8/results/p3c/prefill
```

`run` refuses without `SLURM_JOB_ID` unless `LARB_ALLOW_NO_SLURM=1` is set.
`analyse` is CPU-only but needs the analysis environment for `math_verify`.
