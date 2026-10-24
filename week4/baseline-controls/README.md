# Fixed-budget concurrent controls

[The frozen plan](PLAN.md) compares fixed 2,048 and 4,096 thinking-token budgets with unchanged admission-only and live LARB on exposed development questions. [plan.json](plan.json) records the exact cohort and settings. All new execution code and evidence stay in this folder; historical experiments and controller files remain unchanged.

The staged order is CPU preflight → GPU mechanics gate → late burst → sustained pressure → CPU finalization. The finalizer runs after termination even when inference stages fail or cancel, and labels incomplete results. Only mechanical validity controls continuation, never favorable scientific outcomes. The source/input snapshot is frozen before submission. The gate's known long development question tests real cutoff transport rather than selecting the measured cohort for cuts.

From the repo root:

```bash
python3 -B -m unittest discover -s week4/baseline-controls -p 'test_*.py'
python3 -B week4/baseline-controls/preflight.py --local
```

Cluster launchers accept PACE_PROJECT_ROOT and local SSH configuration; personal login and private folder names stay outside Git. Use the ledger for exact job IDs and resource limits. CPU scoring uses the existing isolated Math-Verify 0.9.0 target, including the tracked baseline/grader/metrics modules; a real saved-result fixture is checked before GPU allocation. Remote dependency declarations and the report allow the chain to finish without a local polling process.

Per-run records contain source snapshots, inputs, calibration/trace hashes, receipts, tokens, worker/scheduler events, mechanical validation, hardware and accounting. Events are archived losslessly; diagnostics are sanitized during collection. The final report includes both static alternatives and all failures, using only 12 unique questions repeated across two conditions and reversed blocks.

Future handoff notes can state which stages finished, where the final report is saved, any failed stage and diagnosis, actual allocation cost, and one next research action. A partial campaign remains partial; nothing automatically reruns a failed or unfavorable experiment.
