# Week 5 — A lane: the one-waiter cut

**Status: implementation, mechanics gate and all three workloads measured and scored.**
[PLAN.md](one-waiter/PLAN.md) holds the frozen design and the two sessions it ran in; this report
holds what was measured, the verdicts and the engineering record.

In one paragraph: the one-waiter cut (`live_one`) recovers fixed-2,048 congestion efficiency under
constant pressure at equal correctness, and behaves exactly as such a trigger should on a changing
load. What it cannot do is create quality. Across twenty-one questions and 141 scored answers, no
policy allowed to think past 2,048 tokens answered a question that fixed-2,048 got wrong; the one
question anybody got wrong, all four policies got wrong.


## 1. What was built (A1)

`live_one` is the Week 4 live rule with one constant changed: the waiting threshold drops from two
requests to one, applied both to the admission decision and to running requests.
[`one-waiter/w5_policy.py`](one-waiter/w5_policy.py) takes the threshold from the policy
(`TRIGGERS = {'live': 2, 'live_one': 1}`) and re-exports the Week 3 state machine and cue
unchanged. The adapter, server and runner are thin Week 5 copies of the Week 4 files, importing
the same `RequestControl`, `policy.forced_token`, `QueueAuditScheduler` and logits forcing path.

Both triggers are selectable in one engine, so `live` and `live_one` can be compared inside one
process on one trace. The Week 3/4 controller files were not edited:
[`one-waiter/test_policy.py`](one-waiter/test_policy.py) verifies their SHA-256 against the Week 4
source lock (and the lock regenerated here still records the identical Week 4 `w4_policy.py` hash).

**13 CPU tests pass** (`python3 -m unittest discover -s . -p 'test_*.py'`). They cover: both
thresholds and their difference at exactly one waiter; admission recorded once, before generation;
fixed policies never changing budget; calibration policy never reacting to load; a single
irreversible reduction; no reduction at zero generated tokens or after natural closure; the cue
running to completion before the answer cap; row moves preserving request identity; and
byte-identity of the reused controller sources.

## 2. Mechanics gate (A2)

The gate ran twice, once per session, on exposed indices 1/4/5 (no cohort question consumed): one
long request started alone, then two more arrived 2.0 s and 2.1 s later so that exactly one request
waited. Both runs pass with no failed check
([session 1](one-waiter/results/job-6663679-gate/mechanical-validation.json),
[session 2](one-waiter/results/job-6665417-gate/mechanical-validation.json)):

| Criterion | Evidence |
| --- | --- |
| Budget decision before generation | Every admitted request carries a scheduler `admission_decision` whose monotonic clock precedes its first streamed token |
| Real overlap | Two requests active in one scheduler step in both gate phases of both runs |
| Cut lands mid-answer under the one-waiter trigger | Session 2: `b0-live_one-001` reduced 16,384 → 2,048 at **123 generated tokens** with exactly one waiter (`…-005`), then the forced cue began at 2,048 and the request finished normally. Session 1 cut at 110 tokens with the same result |
| Fixed transition intact | Every `fixed2048` gate request began the cue at exactly 2,048 tokens with no cap |

The gate also produced the first targeting inputs: the binding cuts had **53.8 s and 55.4 s from cut
to finished answer**, decided **1,938–2,046 tokens before** the short budget, i.e. the cut was cheap in
tokens but expensive in remaining service time.

## 3. Main experiment (A3)

Four policies (`fixed2048`, `fixed4096`, `live`, `live_one`) × two order-reversed blocks × three
workloads, all matched on model, engine, two slots, answer allowance, cue and sampling. Question
slices come from the published SHA-256 rank order of indices 0–99 minus every index Weeks 3–4 used,
one **unspent** slice per condition, so no question carries an answer from an earlier condition.

| Workload | Run | Answers | Phases | Deadline | Measured phase time |
| --- | --- | --- | --- | --- | --- |
| Constant pressure | `job-6663679-constant_pressure` | **48** | 8 of 8 | 122.0 s | 1,389 s |
| One at a time | `job-6665417-one_at_a_time` | **48** | 8 of 8 | 114.0 s | 4,849 s |
| Slack → rush → recovery | `job-6665417-slack_rush_recovery` | **45** | 5 of 8 | 100.8 s | 3,473 s |

Calibration is per job, from two exposed requests with unrestricted thinking; the unit `S` is
`max(30, slowest calibration response)` and every request's deadline is `2·S` from its scheduled
arrival. Reported completion times run from scheduled arrival to final receipt on the client clock,
so they include queueing.


### 3.1 Constant pressure — 48 answers, 6 questions (`19, 67, 87, 39, 27, 35`)

Arrivals `offset(i)=0.3·S·i` with `S = 61.0 s`, so 18.3 s apart, and every request has a 122.0 s
deadline. Two requests were active in one scheduler step in every phase, so this is a real two-slot
queue.

| Policy | On time | Eventual | Median | Mean | Slowest | Mean queue | Thinking tokens | Total output | Cuts / binding |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| fixed2048 | **12/12** | 12/12 | 46.1 s | 49.7 s | 73.4 s | 7.7 s | 22,866 | 28,343 | 0 / 0 |
| fixed4096 | 11/12 | 12/12 | 90.0 s | 85.3 s | 129.2 s | 27.4 s | 32,773 | 38,152 | 0 / 0 |
| live (two waiters) | 12/12 | 12/12 | 76.9 s | 72.5 s | 105.6 s | 17.2 s | 30,867 | 36,767 | 4 / 3 |
| **live_one** | **12/12** | 12/12 | **47.7 s** | 47.8 s | **62.9 s** | 6.0 s | 24,240 | 29,588 | 8 / 7 |

No cap failures and no wrong answers in 48 answers; the only deadline miss is `fixed4096` on question
35 in block 0 (129.2 s). Paired per-question changes (`live_one` − `fixed2048`) are zero on both
on-time and eventual correctness in all 12 question-block cells.

### 3.2 One at a time — 48 answers, 6 questions (`3, 6, 58, 30, 86, 66`)

Arrivals `2·S` apart (`S = 57.0 s`, deadline 114.0 s), so nothing ever waited: mean queue 0.0–0.1 s
and **zero cuts** in all eight phases. This is the workload that answers the premise — what does
extra thinking buy when there is no queue to protect?

| Policy | On time | Eventual | Median | Slowest | Mean queue | Thinking tokens | Total output |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fixed2048 | **12/12** | 12/12 | **35.2 s** | **44.4 s** | 0.1 s | 21,040 | 25,664 |
| fixed4096 | 12/12 | 12/12 | 39.2 s | 65.0 s | 0.1 s | 26,498 | 31,714 |
| live (natural) | 12/12 | 12/12 | 38.6 s | 68.2 s | 0.1 s | 26,608 | 31,762 |
| live_one | 12/12 | 12/12 | 38.1 s | 65.4 s | 0.0 s | 26,608 | 31,762 |

The thinking counts show what actually happened rather than what was allowed. On three of the six
questions the model closes its reasoning below 2,048 tokens by itself (1,048, 1,449 and 1,879), so no
budget can matter there. On the other three it thinks longer when nothing stops it — 2,233, 2,544 and
**4,151** tokens — and `fixed2048` cut those three at 2,048 while `fixed4096` was cut at 4,096 on the
longest. All four policies got all six questions right, in both blocks, on time.

`live` and `live_one` are byte-identical in effect here: same thinking tokens, same output tokens and
same answer in all 12 question-blocks, with no reduction recorded. That is the check the plan asked
for ("the two live policies should behave identically here; if not, something is wrong") and it
passes exactly.

### 3.3 Slack → rush → recovery — 45 answers, 9 questions (`97, 36, 92, 29, 48, 63, 93, 14, 20`)

Arrivals: three slow ones `2·S` apart, then three within 0.1 s of each other after a pause, then
three more `4·S` and `2·S` apart — the shape the plan calls slack → rush → recovery, with
`S = 50.4 s`, deadline 100.8 s and `B ≈ 12 s` between the last slow arrival and the rush. Five of
eight phases ran before the wall-clock cap: block 0 in full and block 1's `live_one` phase only, so
the table is restricted to block 0 to keep the four policies comparable, and the block-1
`live_one` answers are reported separately.

| Policy (block 0, n=9 each) | On time | Eventual | Median | Slowest | Mean queue | Thinking tokens | Cuts / binding |
| --- | --- | --- | --- | --- | --- | --- | --- |
| fixed2048 | **8/9** | 8/9 | **42.5 s** | **89.5 s** | 4.7 s | 17,416 | 0 / 0 |
| fixed4096 | 7/9 | 8/9 | 52.0 s | 131.6 s | 5.7 s | 23,274 | 0 / 0 |
| live (two waiters) | 7/9 | 8/9 | 47.9 s | 132.2 s | 5.1 s | 22,989 | 2 / 1 |
| live_one | 7/9 | 8/9 | 48.7 s | 120.4 s | 5.3 s | 23,459 | 1 / 0 |

Block 1 `live_one` (9 answers, the only phase that fitted): 8/9 on time, 8/9 eventual, median 55.1 s.

Two things separate the policies here. **Question 63**, the third arrival of the rush, is the only
per-question difference: fixed-2,048 finished it in 89.5 s before the 100.8 s deadline, while the
three policies that let thinking run on spent 120–132 s and missed it (all answered it correctly in
the end). **Question 36** is the one wrong answer of the whole study: 4,616 natural thinking tokens,
wrong under all four policies including fixed-2,048.

The one-waiter trigger fired once in block 0 (`…-029`, at **1 generated token**), where the
two-waiter rule fired twice (`…-029` at 5 tokens and `…-092` at 3,019 tokens, the second being the
only binding cut). Early cuts leave the request to think again from 2,048 upwards, so on a sparse
load `live_one` behaves almost exactly like unconstrained thinking — which is why its numbers track
`fixed4096` and `live` rather than fixed-2,048.

## 4. Scoring and coverage (A4)

Grading is the unchanged Week 3 extractor plus Math-Verify 0.9.0 (`analysis-venv`); no parser issues
and no manual corrections were needed, and every failure or cap stays in its denominator. All five
scored runs pass their mechanical audit (`passed: true`, no failures) after one audit-expression
repair recorded in §8.1: the first version compared waiter counts rather than budgets against the
threshold and reported two false failures on the same raw events.

Coverage, from [coverage-audit.json](one-waiter/coverage-audit.json):

| Condition | Expected by this week's coverage | Achieved | Note |
| --- | --- | --- | --- |
| Constant pressure | 48 | **48** | complete, 8/8 phases |
| One at a time | 48 | **48** | complete, 8/8 phases |
| Slack → rush → recovery | 72 | **45** | truncated by its wall-clock cap: block 0 complete, `b1-live_one` complete, `b1-live`, `b1-fixed4096`, `b1-fixed2048` skipped |
| **Total** | 168 (576 in the frozen design) | **141** | 24.5 % of the design, 84 % of this week's coverage |

Every one of the 141 answers has a raw request record, a graded row and a mechanical audit;
136 are correct, and all five wrong answers are question 36, which every policy got wrong in the
block it ran. The three skipped phases are named in `run-complete.json`, not dropped.

The gate answers are excluded from every count above. Each run keeps its raw request records,
worker/scheduler/service event streams, frozen trace, executed sources, hardware, pip freeze and
mechanical audit beside its scores; eight starts that produced no answer are kept next to them with
explicit names (see §8.1). Nothing was dropped, retried for being unfavourable, or removed after the
fact: the only reruns in this lane are runs that never produced an answer.

## 5. Verdicts under the frozen rules

The rules were written in [PLAN.md](one-waiter/PLAN.md) before measurement and are applied unchanged
by [`verdicts.py`](one-waiter/verdicts.py), which reads only the scored rows.

### 5.1 Premise — dead on this cohort

The rule: for extra thinking to be worth anything, `fixed4096` must beat fixed-2,048 on the same
question in **both** blocks with no queue. It does not, on any question, on time or eventually —
and neither does unrestricted thinking (`live`, which closes naturally). Both blocks produced
identical token counts for every policy, so the table shows one row per question.

| Question | Both blocks on time (2048/4096/live/live_one) | Thinking tokens (2048 / 4096 / natural) | Verdict for the premise |
| --- | --- | --- | --- |
| 3 | 1/1/1/1 | 1,879 / 1,879 / 1,879 | closed below 2,048: no budget applies |
| 6 | 1/1/1/1 | 2,048 / 2,544 / 2,544 | thought 496 tokens longer when allowed; same answer |
| 30 | 1/1/1/1 | 2,048 / 4,096 / **4,151** | thought 2,103 tokens longer; `fixed4096` cut at 4,096; same answer |
| 58 | 1/1/1/1 | 2,048 / 2,233 / 2,233 | thought 185 tokens longer; same answer |
| 66 | 1/1/1/1 | 1,449 / 1,449 / 1,449 | closed below 2,048 |
| 86 | 1/1/1/1 | 1,048 / 1,048 / 1,048 | closed below 2,048 |

So the premise fails in the strongest available form: not "more thinking was never tried", but
"more thinking happened, on half the questions, and changed nothing". Three of six questions used
185–2,103 extra thinking tokens when the budget allowed it, and every one of them was already
answered correctly from the 2,048-token cut. The cost side is unambiguous too: `fixed4096` spent
26,498 thinking tokens against 21,040 (+26 %) and 4.0 s of median latency (+11 %) for the same 12
correct answers, so on this pool the longer allowance is pure loss.

### 5.2 Fix, constant pressure — passed

`live_one` equals fixed-2,048 on on-time (12/12) and eventual (12/12) correctness and on median
latency (47.7 vs 46.1 s, +1.6 s), while unchanged two-waiter `live` is **67 % slower** (76.9 vs
46.1 s) with the same correctness. The trigger repair recovers the congestion efficiency the Week 4
diagnosis predicted, and the quality guard (no more than one fewer correct answer) holds with margin.
Cost matches too: `live_one` spent 24,240 thinking tokens against fixed-2,048's 22,866 (+6 %) where
`live` spent 30,867 (+35 %), and its slowest answer was the fastest of the four (62.9 s).

### 5.3 Fix, slack → rush → recovery — passed, on the boundary

Against the frozen rule (`live_one` may not finish with more than one fewer correct answer than
fixed-2,048, on time or eventually), the answer is yes with no margin: block 0 gives `live_one` 7/9
on time against 8/9, and 8/9 eventual against 8/9. The lost answer is **question 63**, lost on timing
only — and `fixed4096` (7/9) and `live` (7/9) lost exactly the same one. So the miss is the price of
thinking longer under a rush, not of the trigger: the three policies that let thinking run past 2,048
spent 120–132 s on a question that fixed-2,048 finished in 89.5 s.

What the workload does show is that the repair is **situational**. Under constant pressure `live_one`
matched fixed-2,048 within 6 % on thinking tokens and 4 % on median latency; under a load that is
mostly slack it is 15 % slower at the median (48.7 vs 42.5 s) and spends 35 % more thinking tokens
(23,459 vs 17,416), because one transient waiter fired exactly one cut in nine answers and the rest
of the time it simply lets the model think. A single waiter is not by itself evidence that shortening
is worth it, which is precisely the question the targeting rule asks.

### 5.4 Targeting ingredients

The shadow-rule lane (C1–C3) needs two numbers, and this week finally delivers them from measured
answers rather than estimates:

- **Service time a cut can free.** Across the pressure and changing-load workloads there are 12
  binding cuts with a measurable cut-to-finish interval: **median 17.1 s, range 5.6–34.2 s**
  (22.1 s median under constant pressure alone; 9.9 s and 12.8 s in the rush). That is the quantity a
  deadline-aware rule would be buying while a specific waiting request tries to make its deadline.
- **When the cut lands.** 17 reductions took effect; **13 fired before the short budget** (18–2,047
  tokens early) and **4 after it had already passed** (+74, +955, +971, +1,259 tokens). Early cuts
  restart the request on a shorter allowance and bind only if the request had more than 2,048 tokens
  of thinking left; late cuts cannot help at all. Both extremes are visible in the same runs.
- **No headroom to exploit on this pool.** The only quality difference in 141 answers is question 36,
  which every policy got wrong. Choosing a different request to cut could not have changed a single
  outcome here, so the discrimination check cannot come out positive on these questions; it needs a
  pool where 2,048 tokens actually costs a correct answer.

## 6. What this means for the path decision

The Week 5 plan's rule is explicit: take the ideal path only if the premise is alive, one-waiter
still leaves a quality gap, and targeting discriminates. None of the three survives contact with the
measurements:

1. **Premise: dead.** With nothing in the queue, `live` thought naturally past 2,048 tokens on
   three of six questions (2,233, 2,544 and 4,151 tokens) and `fixed4096` was given 4,096 by force,
   yet neither won a single question that fixed-2,048 lost — not on time, not eventually, in neither
   block. Extra thinking was available and happened; it bought nothing.
2. **Quality gap: essentially none.** 136 of the 141 answers are correct and the five wrong ones are
   all question 36, wrong under all four policies. Under constant pressure `live_one` matches
   fixed-2,048 on correctness, median latency and thinking tokens while the unchanged two-waiter rule
   is 67 % slower; on a changing load it loses one on-time answer (question 63, which `fixed4096` and
   `live` also lose) and matches it eventually. A smarter trigger cannot recover a quality difference
   that no policy produced.
3. **Targeting: no headroom on this pool.** §5.4 supplies lane C with the two timing numbers its rule
   needs, but with no wrong answer that any cut choice could fix, there is no state in which choosing
   a different request changes an outcome, so the discrimination check cannot come out positive here.

**So the written choice is the backup — a measurement study** — and it now has both halves:
a usable positive result (cutting a running request at the *first* waiter recovers fixed-2,048
congestion efficiency; cutting at the second does not) and a clean negative one (on this question
pool, no policy that thinks past 2,048 answers anything that 2,048 gets wrong). The ideal path is not
refuted, only unsupported: it needs a pool where the 2,048 allowance actually costs a correct answer.
The cheapest next probe is exactly the one the plan reserved — question hardness (lane B5): harder
questions, a smaller model, or a tighter answer allowance, and then re-run the one-at-a-time premise
test, which is the cheapest of the three workloads and the only one that can revive the premise.

## 7. Limits

- **The cohort can barely show a quality difference.** 136 of 141 answers are correct; the single
  wrong question was wrong under every policy, and the single per-question deadline difference came
  from how long thinking ran, not from which request was cut. A verdict of "dead" is therefore a
  statement about *this question pool*: MATH-500 with a 4B model at these settings is not hard enough
  for a 2,048-token allowance to cost correctness. It says nothing about a harder pool or a weaker
  model, which is exactly the change the Week 5 plan reserved for next week.
- **Small, uneven cohorts.** Six questions per workload (nine for the changing-load one), 141 answers
  in total against 576 in the frozen design, and the changing-load workload ran only its first block
  for all four policies plus one extra `live_one` phase, so its comparison rests on nine paired
  questions without an order reversal. Paired per-question changes are reported so that the reader
  can see how little room there is.
- **Pressure is mild.** Mean queue wait was 4.7–27.4 s against 100–122 s deadlines, and the
  changing-load rush is three near-simultaneous arrivals against two slots. Both are real two-slot
  queues, but they produce few misses: nine of 141 answers were not on time in the whole study, five
  of them the wrong question 36 and four the rush question 63 arriving late.
- **One model, one GPU type, one engine configuration, one cue.** All runs share them; the comparison
  would restart if any changed.
- **Deadlines are per session**, two calibration requests each: 122.0 s under constant pressure,
  114.0 s at no load and 100.8 s on the changing load, so absolute seconds are comparable within a
  session rather than across sessions.
- **No targeting system was built here.** §5.4 reports only the inputs lane C needs; the shadow rule
  and the discrimination check belong to that lane.

## 8. Engineering record, cost and environment

### 8.1 What went wrong, and what now prevents it

| Attempt | What happened | Encoded now |
| --- | --- | --- |
| Session 1, allocation 6662944 | H100 killed at 25 min while vLLM loaded: the salloc had **16 GB host memory** (exit 137) | `run_condition.sbatch` requests `--mem=64G` |
| Model download | `huggingface_hub`/`hf_xet` also OOMed on the same limit | `curl` into `LARB-week5-env/model/Qwen3-4B`; the index hash is recorded in every run |
| Session 1, gate → first condition | The terminated server's `EngineCore` child kept 65.6 GB, so the next engine could not start | `launch.sh` anchors its `pkill` to `^VLLM::EngineCore$` and registers an `EXIT` trap |
| Session 1, attempts 2 and 3 | Runner stopped just after calibration on two key-name bugs in `execution.trace_for` | `preflight.py` builds every condition's trace on the CPU in seconds |
| Session 1, validating the pressure run | Two false failures: the audit compared waiter counts instead of budgets against the threshold | audit expression repaired; the same raw events now pass |
| Session 2, attempts 4 and 5 | **The orphan-engine failure recurred.** The gate's `EngineCore` survived the launcher's `pkill` and kept 65.6 GB, so `one_at_a_time` and then `slack_rush_recovery` died at engine start (`ValueError: Free memory on device (14.53/79.22 GiB)`), 46 s and 26 s in | `session2b.sh` hard-kills the PIDs listed by `nvidia-smi --query-compute-apps`, polls until the device is under 2 GiB and refuses to start a condition otherwise. `launch.sh` was deliberately left frozen so the source lock still describes the engine the measured runs used |
| Engine startup | 171 s cold in session 1, **370 s** cold on this node (Lustre page cache), 50 s warm | budget 3–7 min of startup per condition; conditions run back-to-back on one node |

No start that failed produced a measured answer: they are kept as `results/attempt1…attempt8`, and
the three aborted `slack_rush_recovery` starts (attempts 6–8) stopped before their first measured
request. Nothing was rerun because its result was unfavourable — the only reruns in this lane are of
runs that never produced an answer.

### 8.2 Compute actually used

Single H100 80 GB, one condition per process, one allocation per session.

| Session | GPU time | What |
| --- | --- | --- |
| 1, job 6662944 | 25.9 min | OOM-killed while the model loaded; no answer |
| 1, job 6663679 | 37.4 min | gate (7.8 min), three failed condition starts (≈5 min), complete pressure run (24.7 min) |
| 2, job 6665417 | 155.6 min | gate (10.7), two failed engine starts at 46 s and 26 s, two aborted slack starts (≈5.5 min), `one_at_a_time` (82.3), `slack_rush_recovery` (59.8) |
| **Total** | **3.65 h** | of the 16 GPU-hour budget, all on one H100 80 GB with one configuration |

Measured phase time is 4,849 s (`one_at_a_time`) and 3,473 s (`slack_rush_recovery`) against 1,389 s
(the 6-question pressure run): a no-load request costs a fixed `2·S` slot whether or not it uses it,
which is why the premise workload is the expensive one per answer.

### 8.3 Environment (outside git, on shared scratch)

| Path | Contents |
| --- | --- |
| `/home/hice1/jwang3221/scratch/LARB-week5-env/venv` | vLLM 0.11.2, torch 2.9.0+cu128, transformers 4.57.6, aiohttp, fastapi, uvicorn |
| `/home/hice1/jwang3221/scratch/LARB-week5-env/analysis-venv` | math-verify 0.9.0, sympy 1.14.0, latex2sympy2_extended 1.11.0 (grading only) |
| `/home/hice1/jwang3221/scratch/LARB-week5-env/model/Qwen3-4B` | Plain model directory, revision `1cfa9a72…` |
| `/home/hice1/jwang3221/scratch/LARB-week5-env/math500-test.jsonl` | Pinned MATH-500 `test.jsonl`; its first 100 rows rebuilt `inputs/problems100.json` |

## 9. Evidence index

- Frozen plan and provenance: [PLAN.md](one-waiter/PLAN.md), [plan.json](one-waiter/plan.json),
  [cohort.json](one-waiter/cohort.json), [source-lock.json](one-waiter/source-lock.json),
  [genplan.py](one-waiter/genplan.py), [genlock.py](one-waiter/genlock.py)
- Mechanics, tests and gates: [validate5.py](one-waiter/validate5.py),
  [test_policy.py](one-waiter/test_policy.py), [preflight.py](one-waiter/preflight.py),
  [gate run 1](one-waiter/results/job-6663679-gate), [gate run 2](one-waiter/results/job-6665417-gate)
- Measured runs: [pressure](one-waiter/results/job-6663679-constant_pressure),
  [one at a time](one-waiter/results/job-6665417-one_at_a_time),
  [slack → rush → recovery](one-waiter/results/job-6665417-slack_rush_recovery) — each with raw
  request records, worker/scheduler/service events, trace, executed sources, validation and analysis
- Scoring and verdicts: [analyze5.py](one-waiter/analyze5.py), [verdicts.py](one-waiter/verdicts.py),
  [verdicts.json](one-waiter/verdicts.json), [coverage-audit.json](one-waiter/coverage-audit.json)
- Launchers and logs: [launch.sh](one-waiter/launch.sh), [session2.sh](one-waiter/session2.sh),
  [session2b.sh](one-waiter/session2b.sh), [session2c.sh](one-waiter/session2c.sh),
  [session2d.sh](one-waiter/session2d.sh), [run_condition.sbatch](one-waiter/run_condition.sbatch),
  [session2b.log](one-waiter/session2b.log), [session2d.log](one-waiter/session2d.log),
  [scoring.log](one-waiter/scoring.log)
- Failed attempts: [results/README.md](one-waiter/results/README.md)

