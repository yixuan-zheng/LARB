# 7. Scaled rig design

This is the engineering specification for the rig the main path needs. It is deliberately an
extension of the week 5/6 serving package, not a rewrite: the request-local budget contract,
scheduler snapshot, cue forcing, row remapping and failure-preserving record are already correct and
already tested. The new work is concurrency, a capacity-relative pressure rule, realistic traffic,
telemetry, and a resumable phase runner.

## 7.1 Invariants the scaled rig must keep

1. **The engine is real.** vLLM performs admission, batching, KV allocation, preemption and
   sampling. No queue simulation is used for a measured result.
2. **The intervention is real.** A cut changes a running request's budget in the engine and forces
   the transition cue on a subsequent token; it does not re-tokenise or replay the prefix.
3. **Every failure stays.** Caps, timeouts, missing outputs, server errors and late answers remain
   in the denominator and in the raw record.
4. **The contract is explicit.** Whether the opening thinking token counts, whether the cue counts
   against the thinking budget, when the answer allowance starts, and what a naturally closed
   request does are all defined in one module and covered by tests (binder 6.9).
5. **Freeze before measuring.** Sources, model revision, dataset rows, trace bytes, deadlines,
   thresholds and analysis code are hashed before the main run.
6. **Analysis is separable.** A CPU-only script regenerates every headline number from stored
   records; no GPU is needed to audit a result.
7. **Pairing is preserved.** The same question, seed, arrival offset and deadline are used across
   arms within a condition; arms are analysed as paired observations, not as independent samples.

## 7.2 Target configuration

| Item | Main-path value | Notes |
|---|---|---|
| Model | `Qwen/Qwen3-4B`, revision `1cfa9a7208912126459214e8b04321603b3df60c`, BF16 | Unchanged from weeks 3-6. |
| Engine | vLLM 0.11.2, torch 2.9.0, transformers 4.57.6 | Unchanged. The controller imports engine internals; do not upgrade in the main path. |
| `max_num_seqs` | 32 | Gate measures 16, 24 and 32; 32 is the main value if the gate passes. |
| `max_num_batched_tokens` | 8,192 | Must be >= `max_num_seqs`. Prefill is short; 8k is enough. Gate compares 8k and 16k. |
| `max_model_len` | 12,288 | Prompt + 8k thinking + short answer + safety. Not a reservation; KV is allocated on demand. |
| GPU memory utilisation | 0.85, fallback 0.90 | 32 x 8.3k tokens needs about 39 GB of KV plus about 8.2 GB of weights. |
| `enforce_eager` | `False` after the graph gate; `True` fallback | Graphs are where the throughput is. Exact-cue equivalence must pass first. |
| Prefix caching | Off in the main path | Avoids cross-arm cache benefits and run-order effects. Optional extension. |
| Sampling | temperature 0.6, top_p 0.95, top_k 20, per-request seed | Unchanged. Seeds are matched across arms but do not produce matched trajectories. |
| Thinking budgets | short 4,096; full 8,192 | 8k is the serving "full" because 16k x 32 does not fit the KV budget. |
| Answer contract | Legacy 2,048 by default; `short_boxed` only after the bridge gate | The answer phase is a first-order cost (binder 6.5). |
| Deadline | Declared 180 s SLO, from client arrival | Fallback 240 s only if 180 s cannot be calibrated into the 15-40% miss band. |
| GPU | 1 x H100 80 GB, 8 CPUs, 64 GB RAM | `ice-gpu` partition, 16 h maximum. |
| Run output | `week7/scaled-serving/runs/<job-id>/` (gitignored except manifests) | Mirrors the repo's job-directory convention. |

Why 8k and not 16k: the Qwen3-4B KV cache is 147,456 bytes per token (2 x 36 layers x 8 KV heads x
128 head dim x 2 bytes). At 16.3k tokens a request needs 2.4 GB; 32 concurrent requests need 77 GB
of KV alone, which does not fit an 80 GB device with weights. At 8.3k tokens a request needs 1.22 GB;
32 requests need 39 GB, leaving room for weights, activations and graphs. The 16k full-thinking
condition is a separate lower-concurrency bridge, not the main reference. The arithmetic is in
[12-feasibility-notes.md](12-feasibility-notes.md), section 3.

Why 12,288 context rather than 24,576: the main workload never needs more than 8k thinking plus a
short answer. Halving the per-request ceiling roughly doubles the number of sequences that fit if
the engine ever has to reserve the maximum; it also reduces the chance of a long-context outlier
dominating the KV pool.

Why prefix caching is off: the same questions recur across arms and seeds, so a cache-on run would
give later arms cheaper prefill and could make the first arm pay for the cache. The prefill is short
relative to 6-8k decode tokens, so the throughput cost of leaving it off is small. If a later
extension turns it on, the cache must be warmed on filler traffic and the prefill cost reported
separately.

Why CUDA graphs are gated: the controller's logits processor runs in the sampler, outside the model
graph in vLLM v1, so graphs should be compatible. "Should be" is not a measurement. The gate runs
one frozen condition in both modes and compares exact cue positions, token-level outputs on matched
seeds, and throughput. If outputs differ, eager is the main path and graphs are a separate
experiment.

## 7.3 Workload

The workload has two classes. Only the signal class is scored.

| Class | Share of arrivals | Content | Budget | Scored? | Purpose |
|---|---:|---|---:|---|---|
| Signal | 70% | 200-246 hard AIME-family questions | 4k/8k policy | Yes | The quality and deadline endpoint. |
| Filler | 30% | MATH-500 levels 1-2 or GSM8K, disjoint from prior exposure | 1,024 fixed | No | Creates a realistic service-time distribution and keeps the batch full. |

The filler class is not a second quality experiment. It is traffic. It is never included in an
accuracy numerator or denominator, and its budget is below the 4k cut target, so a pressure rule
that cuts toward 4k cannot shorten it. If a filler request naturally closes early, that is expected.
The mix is frozen across arms and conditions.

### 7.3.1 Arrival processes

All traces are generated offline from a seeded process, frozen and hashed before measurement. The
same trace is replayed for every arm in a condition.

- **`sustained`:** Poisson arrivals at a rate chosen by calibration so the reference arm
  (`fixed8k`) misses 15-40% of its **signal** deadlines at 180 s. There is a short warm-up before
  the measured window; the measured window contains the full signal cohort.
- **`burst`:** a low baseline rate, then a burst of signal arrivals at a scripted offset, then a
  recovery period at the baseline rate. The burst must create a real queue and then let it drain.
  This is the condition that exercises hold, cut and restore in one run.
- **`low`:** the same question/seed cohort at a rate far below capacity, so no request waits. This
  is the no-queue control. The queue-aware arms (`arrival`, `live`) should match `fixed8k` here, and
  `live` should log zero cuts; `fixed4k` is the short-budget reference and may differ. If `live`
  cuts, or `arrival` chooses 4,096, in `low`, the controller or the threshold is broken.

The arrival rate is a calibration output, not a hypothesis parameter. It is chosen from the
reference arm's realised miss rate and frozen in the trace. No arm gets its own trace, and no arm's
arrivals depend on its policy.

### 7.3.2 Trace format

One JSON object per line, sorted by `arrival_s`:

```json
{"trace_id":"burst--q0042--s3","condition":"burst",
 "class":"signal","question_id":"aime2026-017","seed":9421,
 "arrival_s":137.42,"deadline_s":180.0,
 "prompt_sha256":"...","reference":"...","source":"MathArena/aime_2026",
 "exposure":"fresh"}
```

Fields:

- `trace_id` is unique within a condition; the replay client adds the arm and constructs the
  runtime `request_id = {condition}--{arm}--{question_id}--{seed}`. The frozen trace itself is
  arm-agnostic, so every arm replays the same bytes.
- `class` is `signal` or `filler`.
- `arrival_s` is relative to the phase start.
- `deadline_s` is the declared SLO (180 s default), not a per-arm calibration.
- `exposure` is `fresh`, `recent` or `exposed`, recorded from the dataset manifest.
- The reference answer and prompt hash are frozen; the prompt text itself lives in the dataset
  snapshot, not duplicated in every trace line.

### 7.3.3 Seeds and pairing

Signal question `q` receives seeds `seed_base + q_index + k * stride` for `k = 0..S-1`, with
`seed_base` frozen per block. The same `(question, seed)` pair appears in every arm and condition.
Filler requests receive their own seeds and are not paired for scoring. The analysis pairs at the
question level, averaging seeds within a question; it does not pretend that matched seeds produce
matched token trajectories.

### 7.3.4 Warm-up and drain

Each phase begins with 20-30 filler requests that are not measured, to warm the engine, capture
CUDA graphs and stabilise allocator behaviour. The phase manager then waits for the engine to drain
before starting the measured arrivals. Between arms, the engine is drained and the KV cache is
allowed to clear; the drain time is recorded. The engine process stays up across phases unless a
crash forces a restart; a restart is recorded and the phase is repeated from its frozen trace.

### 7.3.5 Deadlines

The main-path SLO is **180 s from client arrival** for every request, signal and filler. The
application story is an interactive tutor: a learner should receive an answer within three minutes.
The deadline is not derived from any arm's latency. The calibration chooses the arrival rate that
puts the reference arm in the 15-40% miss band; if no rate does, the SLO itself is revisited before
the main run (240 s is the fallback). A second deadline class (tight/loose tenants) is an
extension, not a main-path feature.

### 7.3.6 What is not varied

Question text, prompt template, sampling parameters, grading, model, engine, cue contract, answer
contract, and the declared SLO are identical across arms. The only thing that differs is the
budget policy. This is what makes the comparison arithmetic rather than rhetorical.


## 7.4 Policies

| Arm | At admission | While running | Budget restoration |
|---|---|---|---|
| `fixed4k` | 4,096, always | Never changes | n/a |
| `fixed8k` | 8,192, always | Never changes | n/a |
| `arrival` | 8,192 if the same-phase waiting count is below threshold, else 4,096; frozen | Never changes | Only new admissions see a changed queue |
| `live` | Same queue-aware rule as `arrival`: 8,192 when waiting is below threshold, 4,096 when at or above it | One irreversible in-flight cut toward 4,096 per pressure step on an eligible running request | New admissions after pressure clears may receive 8,192; a cut request never recovers |

The `arrival` arm is the admission-only control. It uses the same queue snapshot and the same
threshold as `live`, but it makes one decision at HTTP admission and never touches a running
request. The `live` arm is the mechanism. `fixed4k` and `fixed8k` bracket the static alternatives.

### 7.4.1 Pressure

Pressure is capacity-relative, not "a request is waiting":

```
threshold = max(4, ceil(0.25 * max_num_seqs))          # 8 of 32 in the main path
pressure(step) = waiting_same_phase >= threshold
                 for `persistence_steps` consecutive scheduler steps
```

The main path uses `persistence_steps = 2` (roughly one scheduler tick at the measured step rate;
the exact dwell is recorded). A single transient gap does not permanently shorten a request. Gate F
may choose threshold 4, 8 or 12 from the pre-declared grid (12.5%, 25%, 37.5% of slots), then
freezes it. The gate records the fraction of measured steps on which pressure is true in each
condition; a rule that never fires in `sustained` or always fires in `low` is rejected.

The waiting count is filtered to the current phase and arm, so a draining previous phase cannot
trigger a cut in the next one. The snapshot includes the request keys of the waiters so the audit
can reconstruct why a cut fired.

### 7.4.2 Cut rule

When pressure persists, `live` selects **one** eligible running request per scheduler step:

1. It is still in its thinking phase: no close token has been emitted and no cue has started.
2. It has generated at least `progress_floor = 512` tokens (a cut that saves almost nothing is not
   worth the quality risk).
3. Its current budget is above the cut target, and it has at least `min_saving = 1,024` tokens left
   before that budget (a request already at 4,096, or one about to finish, is not cut).
4. Among eligible requests, choose the one with the largest `budget - progress` (the most work
   saved by the cut). Ties are broken by the earliest admission time.

The selected request's budget becomes `min(current_budget, 4,096)` and the change is versioned.
The cue starts on the next controller step at the current token count; the prefix is not replayed.
If the request has already passed 4,096, the cut is immediate. The controller repeats at the next
step only if pressure is still true; this is the cascade that prevents a brief spike from cutting
every running request at once. The cut count, selected request, progress at cut, remaining saving
and pressure snapshot are logged.

`live_all` (the legacy "cut every eligible request at once" rule) is kept as a calibration and
extension arm. It is not the main path because at 32 slots it can cut dozens of requests in
response to one burst, which is neither realistic nor a fair test of a selective mechanism.

The `progress_floor` deliberately excludes zero-progress cuts. Week 6 found that some apparent
in-flight cuts were really admission-timing decisions on requests that had waited before their
first token. Excluding them makes H2 a genuine in-flight test. The cost is that queue relief from
shortening a not-yet-started request is not captured; the entry-timing branch remains a separate
question, tested and rejected once in week 6, and is not folded into this policy.

### 7.4.3 Eligibility and the answer phase

A request that has naturally emitted `</think>` is never cut. A request whose cue has started is
never cut. A request that has hit its answer allowance is finished, not cut. The answer phase is
outside the pressure rule entirely. This preserves the meaning of a cut as a thinking-budget
decision, not a general request killer.

### 7.4.4 Policy assignment and keys

Each phase runs one arm. Request keys are `{condition}--{arm}--{question_id}--{seed}` for signal
requests and `{condition}--{arm}--filler--{index}` for filler. The controller's row map is keyed by
request key, not row index, and follows vLLM's row moves. The pressure snapshot filters by the phase
prefix, so no cross-phase contamination is possible.

### 7.4.5 What is held constant across arms

The admission rule is identical for `arrival` and `live`: both choose 8,192 when the same-phase
waiting count is below threshold and 4,096 when it is at or above it. The cut target is 4,096; the
cue text, answer cap, sampling, prompt, deadline, trace, seeds and grading are identical. The only
difference between `arrival` and `live` is whether a running request admitted at 8,192 can later be
changed. This is what makes H2 an in-flight-intervention test rather than a second admission test.

The admission snapshot is taken at HTTP accept. The gap between HTTP accept and scheduler start is
logged for every request. Re-deciding the budget at engine entry is **not** part of the main path:
week 6 tested that branch and rejected it on a 24-request sample. If the main run shows that most
of `live`'s apparent benefit comes from requests that never generated a token before their cut, the
entry-timing question is reopened as a separate experiment, not folded into this one.

### 7.4.6 Extension policy arms

These are specified now so they are not invented after seeing results:

- `fixed6k`: static 6,096. Tests whether the middle of the grid is the real competitor.
- `live_late`: cut only requests with at least 2,048 tokens of remaining budget and at most 6,144
  generated; a progress-window variant.
- `live_deadline`: cut only when a waiting request is projected to miss its deadline from recent
  service time; the deadline-aware trigger, not the queue-depth trigger.
- `live_probe`: add a coarse confidence/probe signal. This reopens the week 6 branch and is not
  authorised by the main path.


## 7.5 Controller and engine integration

The week 5 controller already does the hard part: it subclasses vLLM's scheduler to snapshot the
queue, registers a logits processor that forces the cue and the terminal token for one row, and
remaps per-request state when vLLM moves rows. The scaled controller keeps that structure and adds
four things.

### 7.5.1 Pure policy core

`policy.py` is a no-vLLM, no-CUDA module. It exposes:

```python
def pressure(waiting, max_num_seqs, threshold_frac=0.25, minimum=4) -> bool
def eligible(state, progress_floor=512, min_saving=1024, cut_to=4096) -> bool
def choose(victims) -> key          # largest remaining budget, earliest arrival tie-break
def apply(state, cut_to=4096) -> bool
```

Unit tests cover: threshold rounding at 16/24/32 slots; persistence; progress floor/ceiling; a
request that is already closed; a request already below 4k; a request with less than min_saving;
tie-breaking; and the one-way property.

### 7.5.2 Request state

The state key is the request key, not the row. The state carries: initial budget, current budget,
budget version, progress, close index, cue start, answer tokens, cut history, policy arm, phase,
arrival timestamp, HTTP accept timestamp, scheduler-start timestamp and deadline. The row map is a
dict keyed by row; `move_rows` handles ADD, REMOVE and SWAP exactly as the existing controller does.
The CPU test simulates 64 rows with random moves and asserts that every request's state follows it.

### 7.5.3 Pressure snapshot and control loop

The scheduler subclass writes a snapshot after each `schedule()` call:

```json
{"step": 18422, "monotonic": 12345.67,
 "running": ["burst--live--q1--s1", "..."],
 "waiting": ["burst--live--q2--s1", "..."],
 "preemptions": {"...": 0}}
```

The logits processor reads the latest snapshot in-process, filters by phase, evaluates the policy
core, and records any cut. The file-backed `pressure.json` used in week 5 is kept for the audit
trail, but the hot path uses an in-process object to avoid a filesystem read per step. The snapshot
is sampled to disk at a stride (default 8 steps) plus full fidelity around cuts; the in-process
copy is always current.

### 7.5.4 Cue and answer contract

The controller forces the exact token IDs of the cue, then the answer cap, then EOS. The legacy
contract is unchanged: a 14-token transition cue, a separate 2,048-token answer allowance, and a
cap counted as a failure. The short contract, if the bridge passes, is a new 128-token answer
allowance opened by a forced `Final answer: \boxed{` cue and closed by a forced `}` before EOS. Both
contracts are implemented behind one interface; the frozen config selects one, and the bridge run
compares them on the same questions.

The contract module is the only place that knows whether the opening thinking token counts, whether
cue tokens count against the thinking budget, where the answer allowance starts, and what a
naturally closed request does. The week 3/5 tests are ported and extended; no measurement is run
against a contract that has not passed them.

### 7.5.5 Graph compatibility

The logits processor runs in the sampler, after the model forward. In vLLM 0.11.2 the model forward
can be captured by CUDA graphs while the sampler remains eager. The gate proves it: one frozen
condition, eager vs graph, compare exact cue positions and token-level outputs on matched seeds. If
the outputs differ, the two modes are different experiments; eager is the main path and graphs are
reported separately.


## 7.6 Telemetry, logs and metrics

Every request record contains:

| Group | Fields |
|---|---|
| Identity | request key, condition, arm, class, question id, seed, source, exposure |
| Times | client arrival, HTTP accept, scheduler start, first token, cue start, close, finish, client receipt |
| Budget | initial budget, final budget, budget path, cut count, cut token positions, progress at cut |
| Tokens | thinking tokens, cue tokens, answer tokens, output tokens, token ids for scored requests |
| Queue | wait seconds, service seconds, latency, queue depth at admission, pressure at admission |
| Outcome | finish reason, normal, cap, error, missing, correct, timely, good, issue |
| System | preemptions, KV blocks at sampled steps, GPU utilisation, GPU memory, phase id |

Per-phase records add throughput, goodput per minute, coverage, horizon, wall time, drain time,
engine restart count, injection lag and the realised waiting-count distribution.

GPU utilisation and memory are sampled at 1 Hz with `nvidia-smi --query-gpu=...` (the login node has
no NVML, but the GPU node does). vLLM's Prometheus endpoint supplies running/waiting counts,
KV-cache usage and preemption counters where available; the scheduler snapshot supplies the
per-request queue state. If a metric is unavailable, it is recorded as null, not imputed.

Log volume: at 10k responses of about 6k output tokens, raw token IDs are about 240 MB, per-request
JSON about 10 MB, and per-step snapshots at stride 8 about 1-3 GB. Full snapshots every step would
be tens of GB, so the default is sampled; full snapshots are retained around every cut and every
phase boundary. A 20 GB per-run cap with compression is the planning number.

### 7.6.1 Metrics that must be reported

- Primary: correct-on-time per scheduled request, numerator and denominator, per arm and condition.
- Marginals: eventual accuracy; deadline attainment; cap rate; missing/error rate.
- Cost: output tokens per request; thinking and answer tokens separately; tokens per correct-on-time
  answer; GPU-seconds per correct-on-time answer; phase throughput (responses/minute, tokens/s).
- Latency: mean, p50, p90, p99 of queue, service and end-to-end latency.
- System: mean/p90 running and waiting counts; fraction of steps under pressure; cuts per phase;
  cut-to-finish time; preemptions; KV occupancy; GPU utilisation.
- Manipulation checks: cue positions exact; no cut after close; no cut of a naturally closed
  request; arrival-only phases have zero in-flight cuts; low-load phases have zero pressure; graph
  and eager cue positions match.

## 7.7 Code layout and build order

```
week7/scaled-serving/
  README.md                      # orientation and index
  PLAN.md                        # execution plan
  binder/                        # 01-06: the information set the plan was written from
  plan/                          # 07-13: design, experiment, main path, risks, sign-off, artifacts
  code/                          # P0 implementation and P1 scaffolding
    larb_scaled/                 # contract, policy, config, workload, stats, server, client, runner
    tools/                       # dataset fetch, cohort/trace build, CPU checks, sweep plans
    tests/                       # CPU unit tests (no GPU or model)
    sbatch/                      # gate and main drafts; they do not submit themselves
  configs/                       # frozen protocol, dataset, gate and main-run configurations
  data/                          # raw and normalized dataset snapshots with manifests
  artifacts/                     # cohort, traces and freeze manifest
  reports/                       # consolidated P0 report
  results/                       # P0 status JSON and dry-run plans
  logs/                          # local logs (gitignored)
  experiment-matrix.csv
  feasibility.py                 # CPU-only checks in plan/12-feasibility-notes.md
  runs/                          # future GPU run outputs; gitignored except manifests
```

The planned `rig/` refactor in earlier drafts is realised as `code/larb_scaled/`; GPU run
outputs will be written under `runs/<job-id>/` once P1 is authorised.

Build order, each with an acceptance test:

1. **Contract and policy core** (pure Python): unit tests from week 3/5 plus the new pressure rules.
2. **Controller adapter**: row-move simulation with 64 rows and random swaps; exact cue token test.
3. **Workload/trace**: a frozen trace validates against the schema, hashes, pairing and deadline.
4. **Server/client**: a 4-request smoke test on CPU (no model) and a 2-request GPU smoke test.
5. **Telemetry**: a synthetic run produces every required field; no nulls where a value is required.
6. **Analysis**: fixture records with known outcomes reproduce a hand-computed goodput table.
7. **Sbatch**: dry-run prints the exact command, paths and expected output; no submission.

The existing week 5/6 files are copied into `rig/` and refactored, not edited in place. The source
lock records both the copied origin and the new hashes. Historical results remain untouched.

## 7.8 What is deliberately not built

No predictor, no priority scheduler, no tensor parallel, no multi-model router, no online threshold
adaptation, no custom attention kernel, no engine upgrade. Each of these would be a new experiment,
not an implementation detail of this one.

