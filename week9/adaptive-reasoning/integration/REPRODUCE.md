# Reproduce or integrate

Run these commands from the repository root. The CPU checks need Python 3.10 or later. The reference runtime needs the [pinned GPU environment and verified adapter](ARTIFACTS.md).

```sh
pkg=week9/adaptive-reasoning
python3 "$pkg/integration/test_policy.py"
python3 "$pkg/figures/build.py"   # matplotlib 3.9.2
reference="$(mktemp -d)/reference"
python3 "$pkg/integration/stage_reference.py" "$reference"
bash -n "$pkg/integration/run-reference.sh"
(cd "$reference" &&
  PILOT_ROOT="$PWD" PYTHONPATH="$PWD:$PWD/repo/week7/scaled-serving/code" \
    "${LARB_PYTHON:-python3}" preflight.py)
```

The CPU HTTP fixture needs aiohttp and NumPy. It exercises the checked-in transport callbacks, phase/replay loop, timing gate, grading and worker-cut reconciliation. The stage uses the committed Week 7 serving package and overlays the final reference files. Use a fresh stage and dedicated local port 18765 for each reference run.

For live archival parity, set `LARB_MODEL_PATH` to the pinned snapshot, `LARB_ADAPTER` to the verified adapter directory, and `LARB_PYTHON` to the pinned vLLM interpreter. From an existing allocated L40S shell run `bash week9/adaptive-reasoning/integration/run-reference.sh /path/to/stage`. The launcher runs the four final probabilistic arms, including an unscored warm-up and timing gate. It does not submit a Slurm job. The [frozen manifest](reference/freeze.json) contains the exact cached and shuffled actions plus both PRNG draws. Use a distinct evidence directory for each run.

To generate cached learned routes for new questions, use the [root-logit extractor](../serving/replication/cache_margins.py) with the repository's pinned GPU environment and the same verified base snapshot and adapter. Set `REPLICATION_ROOT` to a staging directory containing `replication.json` with `blocks[].questions[]` entries carrying `question_id`, `problem`, and `selected` if a prior choice exists. Run:

```sh
export PYTHONPATH="$PWD/week9/adaptive-reasoning/integration/reference"
export REPLICATION_ROOT LARB_MODEL_PATH LARB_ADAPTER
"$LARB_PYTHON" week9/adaptive-reasoning/serving/replication/cache_margins.py
```

Use `measured_choice` (indices 0, 1, 2) in the route cache, keyed by question ID, and record the base, adapter, tokenizer, prompt and extractor version. The constrained one-token sample is used to collect the three token scores. The cache action is the argmax of those scores. If refreshing archived routes, compare `measured_choice` with `cached_choice` before replay. Leave the model fixed across all arms. For deployment record online route latency and tokens separately if routes are computed in the request path.
