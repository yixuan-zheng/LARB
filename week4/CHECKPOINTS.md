# Week 4: checkpoints and actual route

This is the closing record of what happened, rather than a checklist for someone to repeat. The original plan evolved as results exposed more useful questions. The [handoff](HANDOFF.md) summarizes the evidence; [next-week options](NEXT-WEEK.md) gives the incoming lead a starting point.

| Original checkpoint | Final status | What happened / where to look |
| --- | --- | --- |
| 1A–1B: admission boundary and implementation | Complete | Admission-only and live share the initial scheduler decision; live alone can reduce a running budget. [Implementation](step1/admission-control/README.md). |
| 1C: real concurrency validation | Complete | GPU gate passed 176 checks covering admission, overlap, request identity and post-progress interruption. CPU tests were kept distinct from GPU evidence. |
| 2A–2C: controlled development comparison | Complete | Full/arrival/admission/live comparison on 12 exposed questions repeated twice. Live achieved 12/24 correct on time versus admission's 8/24. [Report](step1/controlled-comparison/REPORT.md). |
| 3A–3C: diagnose and select next action | Complete | Timing, correctness changes and cut behavior were assessed. The existing controller was retained for validation; matching seeds were not treated as identical output trajectories. |
| 4A: propose a targeted improvement | Proposal complete; not implemented | Later fixed-budget diagnosis supports a one-waiter trigger ablation. [Diagnosis and proposal](baseline-controls/diagnosis/REPORT.md). |
| 4B–4C: implement and select a revised controller | Deliberately deferred | No revised controller was implemented or evaluated. Current live remains the two-waiter reference. |
| 5A: freeze held-out evaluation | Complete | Exposure audit, 24-question sample, candidate/settings and three traffic conditions frozen. [Plan](evaluation-plan/EVALUATION.md). |
| 5B: execute validation | Complete | Six H100 jobs, 288 measured outcomes, 12 calibration requests; 5.144 GPU-hours. CPU finalization needed a deployment-file repair, without rerunning inference. [Evidence](reserved-validation/README.md). |
| 5C: assess validation | Complete | Pressure correct-on-time 39/96 → 51/96; overall eventual correctness tied at 142/144, with a one-answer pressure quality cost. Benefit strongest under sustained pressure. [Assessment](reserved-validation/REPORT.md). |
| 6A: prior-method comparison planning | Complete, then broadened | Initial LASER/Dynasor/ACER review expanded into an evidence-led audit of five full papers, figures and artifacts. [Audit](literature-audit/REPORT.md). |
| 6B: prepare a prior baseline | Bounded CPU/interface investigation complete; serving integration deferred | LASER-derived policy/contract and 21 CPU checks completed. Probe/rollback, costs and runtime fairness remain unresolved integration work. This is not a running LASER baseline. [Feasibility](laser-feasibility/REPORT.md). |
| 6C: GPU comparison with a prior method | Not run | We chose stronger simple controls and diagnosis before expensive baseline integration. No LASER/Dynasor/ACER superiority claim follows. |
| 7A–7C: package, assess and hand off | Complete | Saved evidence, verified scores, reports, compute accounting, actual checkpoint record and next-week options are packaged. Research continues as a proposal, not an active campaign. |

## Work added because the evidence called for it

**Concurrent fixed-budget controls.** Fixed-2,048, fixed-4,096, admission-only and live ran under matched pressure traces. All GPU stages and CPU finalization completed. There are 192 measured outcomes on 12 repeated exposed questions; gate/calibration bring the raw count to 222. Allocations used 1.738 GPU-hours. [Final comparison](baseline-controls/REPORT.md).

**A stronger challenge to the current policy.** Fixed-2,048 ties live's burst deadline success and beats it under sustained pressure, using fewer tokens. Live still beats admission and fixed-4,096. This separates the value of shortening reasoning from the unproven advantage of our current adaptive rule over strong static choices.

**Offline cut and queue diagnosis.** Question 1 exposes a one-waiter blind spot; question 94 illustrates output variability and the limits of attributing quality changes to cuts. Three sustained cuts arrive after the short budget; five updates never bind. No paired additional-thinking case improves correctness on this small cohort. [Diagnosis](baseline-controls/diagnosis/REPORT.md).

**Deeper literature and artifact audit.** Five full papers were inspected through algorithms, setup and relevant figures/appendices. P-PAS+ public-log arithmetic and request matching were independently reproduced; ACER remains an explicit access gap. We identified strengths, tradeoffs and unresolved questions without treating conceptual overlap as disqualification. [Sources and results](literature-audit/README.md).

## What this week closes, and what it leaves open

We established working live intervention, a load-dependent admission/live benefit, a strong static competitor, concrete policy limitations and a reproducible comparison framework. We have not established broad superiority, population accuracy guarantees, or a completed new algorithm contribution. These limits guide the next study; they do not require a unique idea or a particular prior paper's architecture.

The incoming lead can start with [NEXT-WEEK.md](NEXT-WEEK.md). No jobs are active or awaiting collection. New implementation and inference need a separately frozen plan; none starts automatically from this handoff.
