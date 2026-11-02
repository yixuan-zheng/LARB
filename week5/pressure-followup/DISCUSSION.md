# Review notebook

Stages 1–3 are complete; the reports below record the audited evidence. The checklists describe the review criteria. No background monitor is currently active.

## 1. Mechanics gate — completed; review available

- [x] Inspect terminal job state and preserve the Slurm log,raw outputs and worker events privately.
- [x] Verify both actual cue starts:4096 and5000tokens;normal EOS and unchanged answer allowance.
- [x] Distinguish synthetic pressure/masking from real scheduler-pressure behavior.
- [x] Decide:ready for separately authorized calibration,or diagnose failure without automatic rerun?

**Discussion:**What did we learn beyond the prior Week5 controller tests? Which guarantees remain CPU-only or untested under real batching?

**Evidence / decision:**[Stage 1 report](STAGE1-REPORT.md):both boundaries pass;recommend separately scoped calibration.

## 2. Calibration — completed; timing audit passed

- [x] Inspect actual queue occupancy,arrival-to-start delay,and completion times.
- [x] Check intended low/near/burst conditions against observed behavior.
- [x] Freeze trace,source hash,deadline recipe,and resource envelope before measurement.

**Discussion:**Does the chosen scale genuinely create an informative operating boundary? Should an arrival-only control be included immediately,or reserved for a positive pilot follow-up?

**Evidence / decision:**[Stage 2 report](STAGE2-REPORT.md):8/8 records audited;no waiting observed. Review the [Stage 3 real-queue gate proposal](STAGE3-PLAN.md).

## 3. Measured pilot — completed; primary goodput superiority not demonstrated

- [x] Compare correct on-time goodput against both fixed budgets using matched traces.
- [x] Show quality loss,deadline misses,interventions,and recovery—not just token savings.
- [x] Preserve fixed denominators and all failures;review extraction before accuracy claims.

**Discussion:**If fixed4K wins,is adaptation adding useful complexity? If live wins,what fresh problems,repeated traces,and arrival-only ablation are needed before a research claim?

**Evidence / decision:**[Stage 3 report](STAGE3-REPORT.md):live ties8Kgoodput with lower latency/tokens. Discuss arrival-only ablation and independent repetitions before a larger study.

## 4. Follow-up — cancelled before execution, not a negative result

Both sequential allocations were cancelled by the user ahead of maintenance. Neither started; zero responses were produced. No follow-up effect estimate exists, and no job or background monitor remains active.

**Next review:** Does live intervention add value beyond choosing the budget at arrival? The [follow-up plan](FOLLOWUP-PLAN.md) preserves four policies, two matched blocks, fixed traces, and 160 measured responses plus eight engineering probes. Favor arrival-only if it matches live's quality and cost. Report reversals between blocks rather than selecting a favorable run. All reused AIME2025 questions remain development data.

**Before restarting:** confirm cluster restoration and runtime compatibility, review the frozen source and traces, and authorize replacement allocations explicitly. Do not tune deadlines or drop capped outcomes based on the completed pilot. Fresh tasks and broader load validation come after this mechanism comparison, not from treating repeated questions as independent evidence.
