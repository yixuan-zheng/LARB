# Asynchronous agent RL scheduling — initial results

**Status: preliminary research, not a demonstrated scheduler improvement.** We have a working native training setup, execution traces, a rollout-to-learner diagnosis, and an executed GroupGate prototype comparison. The prototype changes request order but has not shown a repeatable delivery advantage over strong ordinary controls. Positive learning-efficiency improvement is not established.

## Research question

Can coordinating new rollout starts and unfinished trajectory groups deliver useful, sufficiently fresh training data more efficiently than existing asynchronous RL controls?

GroupGate is one prototype, not the definition of the direction. It prioritizes pending generation requests from groups with observed terminal reward variation, preserving all four group members and using age promotion to prevent starvation. Reward variation identifies mixed-group filter eligibility, not guaranteed learning value.

## Start here

- [RESULTS.md](RESULTS.md): compact numerical findings, limitations, and current research decision.
- [docs/comparison-assessment.md](docs/comparison-assessment.md): latest actual scheduler comparison.
- [docs/diagnosis-assessment.md](docs/diagnosis-assessment.md): reconstructed learner/data timeline.
- [docs/pilot-assessment.md](docs/pilot-assessment.md): native training pilot and quality results.

| Directory | Contents |
|---|---|
| `code/prototype/` | GroupGate and correctness checks |
| `code/comparison/` | Fixed-policy TIR comparison, analyzer, telemetry collector, and launch templates |
| `code/pilot/` | Native training workflow wrappers and configurations |
| `code/diagnosis/` | Trace timeline analysis |
| `results/` | Tables, JSON summaries, exact prompt manifests, and essential raw traces/logs |
| `provenance/` | Framework/model revisions, observed environment, and upstream license |

Excluded: model weights, virtual environments, framework checkout, checkpoints, duplicate archives, unrelated research, unexecuted lookup adapters, and the many failed qualification/debugging attempts. This is a curated initial-results package, not a complete experiment-history backup. Raw logs retain original cluster paths and timestamps; no credentials are required to analyze them.

## Recompute the main measurements — no GPU needed

From this directory, using Python 3.10 or newer:

```bash
python3 reproduce_analysis.py
python3 code/prototype/test_group_gate.py
```

The first command reconstructs the directory layout expected by the original analyzers in a temporary directory, recomputes the rollout diagnosis and GroupGate comparison, checks their main JSON outputs against the saved outputs (allowing floating-point summation roundoff), and writes regenerated files under `analysis-output/`. It uses only the Python standard library. This checks analysis reproducibility from recorded data; it does not reproduce GPU execution or remove the original experimental limitations.

## Rerun the real comparison — GPU environment required

This is not a one-command portable environment installer. Use the pinned AReaL revision and compatible CUDA/vLLM stack in `provenance/`. The observed environment freeze is a reference snapshot, not a minimal installation specification. Model revision is pinned in `provenance/model.json`.

1. Set `AGENT_RL_ROOT` to an experiment directory containing the pinned framework checkout as `areal/`, compatible environment as `env/`, and the pinned model as `model/`.
2. Copy `code/comparison/*.py`, `code/comparison/tirgatecompare.yaml`, `code/prototype/group_gate.py`, and `code/pilot/{tools_profile,profile_workflow}.py` into that directory.
3. Reconstruct the original dataset rows with `python3 prepare_data.py "$AGENT_RL_ROOT"`. This needs the `datasets` package already present in the GPU environment. It validates the exact comparison prompts against the included run manifest.
4. Review `code/comparison/job.sh` for your cluster's partition/resource syntax. Its experiment root and YAML paths use `AGENT_RL_ROOT`; edit the launcher rather than assuming PACE resources exist elsewhere.
5. Submit the job with `AGENT_RL_ROOT` exported. The script sets the required Python paths, uses one persistent engine, and runs all phases. Use a new `profiles/tirgatecompare` directory for each run.

The comparison uses a fixed policy and finite cohorts with native mixed-group filtering; rejected groups are not replenished as in trainer dynamic sampling. It therefore measures delivery and full-drain costs, not learning or policy freshness. Four-member group concurrency and per-generation gate capacity are different units. The native arm runs first, creating cache-order limitations. Identical per-request seeds did not give identical trajectories across repeated GPU runs; do not assume deterministic reproduction.

Pilot training also needs `data-test/` (created by `prepare_data.py`) and the original dependencies. Its key results are included, but the lightweight reproduction command intentionally recomputes only the two standard-library analyses. The third-party framework and GSM8K/Qwen assets retain their respective upstream terms; this package does not relicense them.

## Integrity

`SHA256SUMS` covers every packaged file except itself. The ZIP has a single top-level directory. No experiments are launched by opening this package or running the CPU analysis command.
