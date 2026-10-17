# Native TIR GroupGate comparison: completed

The requested native/FIFO/GroupGate comparison completed. The prototype operated under real contention and changed order, but it did not establish a repeatable useful-delivery benefit over FIFO or an advantage over native admission. This is the first executed scheduling-effect comparison, not another workload qualification failure.

## Setup and integrity

AReaL ba237a1b21703417541c2f107adb923d8ca1f504; cached Qwen2.5-1.5B-Instruct; native vLLM0.19.1; upstream calculator TIR and math verifier; actual calculator execution, no injected delay. One 48GB-visible Blackwell MIG instance, two allocated CPU cores. Fixed policy, no actor/optimizer/training. Native concurrency16 counts trajectory groups (up to64 episodes), while external capacities16/8 count outstanding generation calls. These are different units, and the native arm bypasses the external limiter.

Preflight:16 valid episodes,3 mixed groups. Six comparison phases each run the same16 source prompts and four members/group, with identical native mixed-group filtering and per-request seeds derived from source/member/call. Total400 valid episodes (384comparison +16preflight). All returned groups have four distinct members, and worker filter calls each see four reward rows. Returned counts exactly equal raw mixed-group counts in every phase. Every finite cohort drains, including rejected groups; no reward group or unfinished work is canceled. This finite filter rejects without replenishment, unlike trainer dynamic sampling. Completion timestamps are worker filter callbacks, before final trajectory dump/transport; phase walltime includes root return.

## Actual results

| Arm, chronological order | Drained walltime | Accepted mixed groups | Generated tokens | Time to8 mixed groups | Priority reorders |
|---|---:|---:|---:|---:|---:|
| Native admission |34.13s|12|52,313|29.50s|—|
| FIFO16 |37.95s|10|38,737|34.02s|0|
| GroupGate16 |37.85s|12|35,581|16.89s|16|
| FIFO8 |48.67s|8|37,081|48.66s|0|
| GroupGate16 repeat |41.17s|9|55,582|32.21s|18|
| FIFO16 repeat |43.49s|11|46,033|26.69s|0|

GroupGate makes actual non-FIFO admissions:16/169 and18/210 requests. Capacity16 gates see queue depth47. Mean drained walltime is39.51s GroupGate versus40.72s FIFO16, approximately3% lower, but that descriptive difference is smaller than observed run variation and workloads differ. It is not an established scheduler speedup. Time-to8 improves50.3% in the first pair but worsens20.7% in the repeat. Four source groups are mixed across every arm; time until those four complete also reverses:23.30s vs34.13s first pair,40.61s vs23.35s repeat. Restricting to common sources therefore does not rescue a consistent claim.

Native has the shortest observed drained walltime and highest accepted-group rate,0.352/s, versus0.317/s and0.219/s for GroupGate and0.264/s and0.253/s for FIFO16. Native is measured once and sees comparison prefixes first; later arms can benefit from warmed prefix caches. This is not a statistically established native dominance claim, but it gives no reason to prefer an external cap16 scheduler here.

## Important confound: stable seeds did not give identical trajectories

Relative to native,12–16 of64 terminal outcomes differ across comparison arms. Even repeated identical policies differ:15/64 rewards for FIFO16 and16/64 for GroupGate16. Across all phases, generated token counts vary35,581–55,582. The proxy supplies stable per-request seeds, and native vLLM request construction forwards gconfig.seed. Those controls do not guarantee identical execution under different backend batching and cache state. We did not isolate the nondeterminism's precise cause. Backend numerical/batching sensitivity is a plausible explanation, not a demonstrated root cause. Do not attribute reward changes, different accepted counts, or all walltime differences causally to scheduling. These are fixed-policy trajectory outcomes, not learning progress.

## Engine and gate bottleneck diagnosis

Two-second engine samples observe zero backend waiting requests and zero preemptions in every phase. Native reaches62 running requests, external cap16 arms peak16, cap8 peaks8. Peak KV occupancy across comparison phases remains below3%. Low KV occupancy does not measure compute utilization or prove unlimited capacity; sampling can miss short queues. Nevertheless, the persistent observed request queue is in our external gate, not vLLM. Gate16 median waits are about1.9–2.8s, with maximum6.5–7.9s. Gate8 median is4.84s and maximum12.76s.

This explains a design risk: we created a narrower admission point to enable reordering, while the native engine could run more requests without observed memory pressure. Priority can rearrange that artificial backlog, but must overcome the batching/concurrency benefit it removes. Learner waiting in earlier runs does not imply that this external cap is the right control point.

## Research decision

Do not scale up this exact fixed-cap GroupGate rule or start a learning campaign on its current evidence. Keep it as a working experimental mechanism. The broad coordination direction remains open, but this cohort supplies negative evidence against expecting an easy robust gain from known-mixed priority behind cap16. It does not establish that every group-aware scheduler fails, nor that the broader problem is solved.

The simplest useful revision is to separate concurrency from priority: preserve the native engine's feasible parallelism and prioritize only when a real admission/resource limit binds. A next bounded comparison could vary native group concurrency to determine where waiting, KV pressure, or throughput saturation actually appears, then test FIFO versus priority at that same binding limit. This is a proposed next step, not an executed result. Do not add reward, age, and learner-demand heuristics indiscriminately. If no realistic pressure regime exposes a completion-versus-start tradeoff, reconsider this scheduler direction. A reproducibility check is necessary before attributing small delivery gains to a policy.

## Cost, artifacts, and limitations

Slurm6278460 COMPLETED after757 allocation seconds:0.2103 MIG-instance-hours, not full-GPU hours. About7.9minutes elapsed before preflight began; all seven phases together took about278s, of which243s were comparison. No active jobs remain. All startup, evaluation-only generation, rejected data, and drain time are charged to the allocation. There is no measured learning-per-GPU-hour result, no policy staleness experiment, no inference placement change, and no simulator of scheduler performance.

results.json, checks.json, comparison.csv and delivery-curves.csv hold measurements. engine-summary.json contains phase-bounded metric summaries; counters are cumulative within the engine and must not be interpreted as per-phase counts. raw-important.tar.gz preserves worker traces, exact prompt manifest, engine metrics, logs, hardware and model provenance. Source scripts/config and checksums are bundled in reproduction.zip. Upstream model weights stay on PACE. All comparison checks passed, the GroupGate capacity/priority/fairness/cancellation unit checks passed, and the external adapter scripts compile. Full native distributed integration tests were not run; this experiment uses one rollout worker.
