# 9. The main path

This is the minimal line that can produce a clean result in a reasonable time. It is ordered from
the cheapest and most informative checks to the most expensive. Each step has an output, a pass
criterion and a fallback. A step that fails stops the line; it is not papered over with a retry or a
threshold change.

## 9.1 The line in one table

| ID | Step | Cost | Output | Pass / stop |
|---|---|---|---|---|
| P0.1 | Freeze protocol, arms, endpoints, stopping rules | CPU, 0.5 day | `PROTOCOL.md` | Owner signs; no open design item |
| P0.2 | Acquire and QC the 2025-2026 signal pools + filler + screening pools | CPU, 1 day | `DATASETS.md`, manifest, hashes | 200-246 gradable signal items; licenses recorded |
| P0.3 | Build and validate the trace generator | CPU, 0.5 day | `TRACE.jsonl` per condition + SHA-256 | Schema, pairing, deadlines, counts valid |
| P0.4 | Port the controller/policy/analysis; write CPU tests | CPU, 2-3 days | `rig/`, test report | All contract, row-move, policy and analysis tests pass |
| P0.5 | Synthetic queue rehearsal and power calculation | CPU, 0.5 day | Rehearsal report | Pressure fires in the intended band; MDE recorded |
| P1.0 | GPU rig bridge: AIME 2025, 2 seeds, fixed4k/fixed8k | 0.5 h | Bridge report | Within ~10 points of the saved 36.7% / 45.0% |
| P1.1 | GPU gate A: 32-row mechanics and exact cue | 1 h | Gate A report | Exact cue, no crash, no state loss |
| P1.2 | GPU gate B: eager vs CUDA graphs | 0.5 h | Gate B report | Same cue positions and tokens; throughput measured |
| P1.3 | GPU gate C: concurrency/throughput sweep | 1 h | Throughput curve | Pick 32 or fall back to 24/16; N decided |
| P1.4 | GPU gate D: answer-contract bridge | 1 h | Contract report | Legacy or short selected |
| P1.5 | GPU gate E: slope screen | 1 h | Slope report | Pool passes 8-point / 10%-change criterion |
| P1.6 | GPU gate F: load and deadline calibration | 1 h | Calibration report | Reference miss rate in 15-40% |
| P2.1 | Freeze main config, trace and source lock | CPU, 0.2 day | `source-lock.json` | Hashes match; no uncommitted change |
| P2.2 | Main run: low, sustained, burst phases | 10-16 h | Raw records + phase summaries | Coverage and manipulation checks pass |
| P3.1 | Grade, audit, analyse | CPU, 1 day | `analysis.json` | Primary CI computed; checks pass |
| P3.2 | Write report and reproduction | CPU, 0.5 day | `REPORT.md`, `reproduce.py` | Every headline number reproduces |
| P3.3 | Decide H1-H4 and authorise or refuse P4 | CPU, 0.1 day | Decision memo | One of the PLAN.md section 5 outcomes |

The GPU gate job (P1) is one 6-8 h allocation. The main run (P2) is one 16 h allocation. The main
path is P0-P3. P4 is conditional.

## 9.2 P0: protocol, data and CPU code

### P0.1 Protocol

Write `PROTOCOL.md` with: the hypothesis and H1-H4; the four arms and their exact rules; the three
conditions; the declared 180 s SLO; the pressure threshold, persistence, progress window and cut
target; the cohort and seed rule; the primary endpoint and denominator; the three pre-registered
comparisons and the multiplicity rule; the stopping rules; the exclusions and failure handling; and
the artifact list. Nothing in the protocol may depend on a model outcome.

### P0.2 Datasets

Download the MathArena datasets and the filler pool. For each: record the dataset id, revision,
file hash, license, row count, answer format and exposure tag. Normalise to one schema
(`question_id`, `problem`, `answer`, `source`, `exposure`). Run the exclusion rules in
[08-experiment-design.md](08-experiment-design.md), section 8.2.3. Freeze the manifest. Do not run a
model to choose items.

### P0.3 Trace generator

Implement the arrival processes, question/seed assignment, filler interleaving and trace schema.
Generate the three condition traces. Validate that every arm in a condition has the same question,
seed, arrival offset and deadline. Hash the trace bytes. The trace generator is part of the source
lock.

### P0.4 Rig and tests

Port the week 5/6 code into `rig/`. The acceptance tests:

- Contract: opening-token accounting, cue-token accounting, answer-cap start, natural close, forced
  EOS, short-vs-legacy contract switch.
- Policy: threshold rounding, persistence, eligibility, progress floor/ceiling, largest-remaining-
  budget choice, one-way cut, no cut after close.
- Controller: 64 simulated rows with random ADD/REMOVE/SWAP; every request's state follows its key;
  exact cue token for a row that is not row zero.
- Workload: schema, pairing, hashes, deadline, counts.
- Analysis: fixture outcomes reproduce a hand-computed goodput table; caps and missing records stay
  in the denominator.
- Sbatch: dry-run prints the exact command; no submission.

### P0.5 Synthetic rehearsal

Run a pure-Python multi-server queue with the measured service-time distributions and the frozen
traces. Check that the threshold fires in `sustained`/`burst` and not in `low`; check that the
cascade can relieve the queue; estimate the phase durations. This is a design check, not a result.
Record the power calculation from [12-feasibility-notes.md](12-feasibility-notes.md) in the
protocol.

## 9.3 P1: the GPU gate job

One allocation, 1 H100, 8 CPUs, 64 GB RAM, 8 h outer cap, 6-7 h inner timeout. The gates run in
order; a failed gate stops the job and preserves its records. No gate result is a hypothesis result.

### P1.0 Rig bridge

Run 30 AIME 2025 questions x 2 seeds x `fixed4k` and `fixed8k` with the legacy cue/answer contract.
Compare with the saved week 5 screen (4k 36.7%, 8k 45.0% on 60 responses per budget). The bridge is
a rig-validity check, not a hypothesis result. If either budget differs by more than about 10
points, stop and debug the prompt, grading, cue or engine configuration before running the other
gates. The bridge questions are not in the main cohort.

### P1.1 Gate A: 32-row mechanics and exact cue

- Launch the engine with `max_num_seqs=32`, `max_num_batched_tokens=8192`, `max_model_len=12288`,
  `enforce_eager=True`, prefix caching off.
- Send 32 concurrent requests with known prompts and budgets, including requests on non-zero rows,
  natural closes, a forced cue, and an answer cap.
- Force enough completions and admissions to create row moves and at least one preemption if the KV
  pressure is real; if no preemption occurs, record that and do not claim one.
- Verify every cue starts at the exact intended output position, every row's state follows its key,
  no cut happens after close, and no request is lost.
- Pass: exact positions and state for all 32; a second run with a different arrival order passes.
- Stop: any off-by-one, lost state, or cut after close. Fix the controller; do not proceed.

### P1.2 Gate B: eager vs CUDA graphs

- Run one frozen 32-request condition in eager and in graph mode (`enforce_eager=False`).
- Compare exact cue positions, token IDs on the same seed and prompt, completion reasons, and
  throughput.
- Pass: cue positions identical; token-level outputs identical or the difference is explained by a
  documented nondeterminism; graph mode is faster.
- If outputs differ: the two modes are separate experiments. Keep eager for the main run; report
  graphs separately, or disable graphs.

### P1.3 Gate C: concurrency and throughput sweep

- Fixed prompt and generation length (e.g., 4,096 thinking + 128 answer), 5 minutes per point; add
  one 8,192-thinking point at the chosen concurrency so the N estimate uses the arm-average length,
  not only the short-budget rate.
- Concurrency 1, 2, 4, 8, 16, 24, 32. Record output tokens/s, per-request latency, KV occupancy,
  preemptions, GPU utilisation and queueing.
- Fit the throughput curve and decide the main concurrency. If 32 is slower than 16 because of KV
  pressure or scheduling overhead, use the knee (likely 16-24) and record why.
- Decide N for the main run from the measured arm-average output length (about 6k tokens): the full
  4-seed, 10,520-request design needs at least about 1,500 output tokens/s to fit a 16 h job with
  phase overhead. Use 3 seeds at 1,200-1,500 and 2 seeds at 1,000-1,200; below 1,000, split the run
  into two jobs. Never set N from a hoped-for rate.

### P1.4 Gate D: answer-contract bridge

Run the 384-response bridge in [08-experiment-design.md](08-experiment-design.md), section 8.4.
Select legacy or short. If short passes, re-run a 32-row mechanics check under the short contract
before the main run. If short fails, use legacy and recompute the main-run N (the answer phase is
about 18-20% of output tokens at 8k thinking; the throughput difference is real but not fatal).

### P1.5 Gate E: slope screen

Run the 216-response screen in [08-experiment-design.md](08-experiment-design.md), section 8.3:
144 responses on disjoint 2023-2024 questions plus 72 on a 24-question preview of the main cohort.
The preview decides whether the main run proceeds; the main cohort loses those 24 items. Pass/fail
the pool. If it fails, stop and change the pool; do not run the main experiment on a flat pool.
Record the 4k/6k/8k accuracy and the question-level answer changes.

### P1.6 Gate F: load and deadline calibration

- Use the 48 screening questions plus filler, not the main cohort.
- Run `fixed8k` at 3-4 candidate arrival rates around the roofline capacity estimate.
- For each, record the realised queue, service time, miss rate at 180 s, and GPU utilisation.
- Choose the rate that puts `fixed8k` **signal** requests at 20-30% misses (inside the 15-40% band)
  and keeps the GPU busy without preemption storms.
- Record the fraction of measured steps under pressure at each rate. Target a non-trivial fraction
  (roughly 5-50%) in `sustained`/`burst` and near zero in `low`. If the pre-declared threshold of 8
  of 32 gives no pressure or constant pressure, try the pre-declared alternatives 4 (12.5%) or 12
  (37.5%) and record the choice; do not invent a new rule after seeing outcomes.
- Freeze the arrival rate, threshold, persistence, trace and deadline. If no rate produces the
  band, revise the SLO to 240 s and repeat; do not tune the deadline after seeing a policy
  comparison.
- Also run a 30-minute `live` manipulation check: pressure fires, cuts land, the queue falls, and
  new admissions recover to 8k. This is a mechanism check, not a quality result.

### P1.7 Gate exit

Freeze: config, threshold, persistence, progress window, cut target, answer contract, concurrency,
arrival rate, trace, source hashes and analysis code. Write `source-lock.json`. The main run uses
exactly these bytes. No gate-result-dependent tuning after this point.


## 9.4 P2: the main run

One 16 h allocation. The phase runner is resumable; each phase writes a manifest and a summary. If
the job reaches its time limit, the next job runs only the missing phases from the frozen trace.

Slurm envelope: `--partition=ice-gpu`, one H100, 8 CPUs, 64 GB RAM, `--time=16:00:00`; the serving
venv at `/storage/.../LARB-week5-env/venv`; `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`; model path
from the frozen model directory; `srun --kill-on-bad-exit=1 timeout --signal=TERM --kill-after=30s
15h ...`; outputs under `week7/scaled-serving/runs/<job-id>-main/`. The gate job uses the same
envelope with an 8 h limit. No `sbatch` submission is made by this plan.

Order:

1. Warm-up and `low` control: fixed4k, fixed8k, arrival, live (about 2-2.5 h for all four phases).
   This is also the end-to-end dress rehearsal: if the phase runner, telemetry or analysis pipeline
   fails, it fails here before the expensive pressure phases.
2. `sustained`: fixed4k, fixed8k, arrival, live (about 5.5-6 h at the conservative rate).
3. `burst`: live, arrival, fixed8k, fixed4k (about 6.5-7.5 h).
4. If time remains, a second `sustained` block in reverse order (extension).

Each phase: warm-up fillers, drain, measured trace, drain, summary. Record the phase start/end,
wall time, drain time, coverage, injection lag, engine restarts and the realised queue statistics.

Pass: all phases present; coverage complete; injection lag < 1 s; no phase silently truncated;
manipulation checks from 08-experiment-design.md, section 8.7.3 pass. If a phase fails, rerun only
that phase; do not drop the arm.

## 9.5 P3: analysis and report

1. Grade every response with the frozen grader; write raw, parsed, correct, normal, timely and good
   flags; build the manual-review queue.
2. Recompute the per-question pairs; run the cluster bootstrap and the McNemar/permutation tests.
3. Produce the marginals and system metrics; check the manipulation reports.
4. Write `analysis.json` and `REPORT.md` with the pre-registered structure: primary, secondary,
   heterogeneity, failures, limitations, decision.
5. Run `reproduce.py` from a clean directory; it must regenerate the headline numbers from the
   stored records without a GPU.
6. Write the decision memo: H1/H2/H3/H4 supported, refuted or unresolved; one of the PLAN.md
   section 5 outcomes; the next action.

## 9.6 P4: conditional extension

Authorised only by a specific P3 outcome:

- **Resolution extension:** 500-800 questions or a second block, if the effect is 2-5 points with a
  CI spanning zero. This is the only path to a 3-point claim.
- **Policy extension:** `live_late`, `live_deadline`, `live_cascade` variants, if `live` beats
  `fixed4k` but loses too much accuracy against `fixed8k`.
- **Static extension:** `fixed6k` in the main conditions, if the slope screen says it is
  competitive.
- **Full-thinking bridge:** `fixed16k` at 12-16 slots on a subset, to connect the 8k serving
  reference to the original 16k full-thinking claim. It is not part of the 32-way main path.
- **Model bridge:** Qwen3-8B at a lower concurrency, if the 4B result is positive and the question
  is whether it transfers.
- **Replication:** a second block on a different seed base, if run-order or seed instability is the
  main threat.

## 9.7 Budget and calendar

| Item | GPU hours | Calendar |
|---|---:|---|
| P0 CPU | 0 | 3-5 days |
| P1 gates | 6-8 | 1 day (one allocation) |
| P2 main | 10-16 | 1 day (one allocation) |
| P3 analysis | 0 | 1-2 days |
| P4 extension | 16+ | 1-2 weeks, conditional |
| **Main path total** | **16-24 GPU hours** | **2-3 weeks** |

The main path is deliberately one gate job and one main job. It does not require a multi-week
campaign, and it produces a decision even if the answer is "not supported."

