# 6A: closest-method comparison and novelty boundary

Reviewed 2026-10-22. [sources.json](sources.json) records primary URLs, versions, inspected material, code pin, and gaps. This is a targeted comparison specification. No external baseline has been integrated or benchmarked, and novelty remains unresolved.

## What the inspected methods cover

**LASER is the closest load-aware comparison.** Its active-request load signal drives an EMA-smoothed early-exit confidence threshold; prompt length and load also determine an initial chunk budget. Trial-answer probes occur at action-transition points. The paper specifies the threshold and budget equations and reports a FIFO discrete-event serving simulation. Its stated decision inputs do not explicitly forecast which waiting requests a particular active-request cut would rescue; that is an interpretation of the inspected algorithm, not an exhaustive absence claim. The defaults target a different serving setup. In our two-slot engine, active count saturates quickly: substituting queue length would change the method. [Paper, §§3–5, Algorithm 1, Eqs. 5–8](https://arxiv.org/html/2606.31580v1).

**Dynasor is the closest progress-aware systems comparison.** Certaindex monitors answer stability and guides compute allocation. The full system also includes profiling, gang scheduling, and estimated shortest-job-first ordering. The paper therefore already covers cross-program resource coordination broadly; “consider multiple requests” is insufficient differentiation. Its CoT mechanism needs intermediate-answer probes, whose full latency and compute belong in a comparison. [Paper, §§2–4 and Appendix D](https://arxiv.org/html/2412.20993v2).

The [public implementation](https://github.com/hao-ai-lab/Dynasor/tree/0d2f1b93a60e031cfc7fb43843d2b736b225960c) supplies CLI/native-server routes, but public helper behavior and full-paper scheduling should not be treated as interchangeable. Static inspection found substantial vLLM-internal imports; compatibility with our pinned runtime has not been established. The README recommends prefix caching for probing, unlike our current cache-disabled gate. The pinned stopping helper has a terminal return that accepts inconsistent/empty/earlier-uncertain windows once earlier guards pass. [Six CPU cases](upstream-audit.json) reproduce three discrepancies against its documented consistency contract. This is a scoped code finding, not evidence that the paper's complete system fails. [Helper](https://github.com/hao-ai-lab/Dynasor/blob/0d2f1b93a60e031cfc7fb43843d2b736b225960c/dynasor/core/entropy.py), [server path](https://github.com/hao-ai-lab/Dynasor/blob/0d2f1b93a60e031cfc7fb43843d2b736b225960c/dynasor/cli/vllm_server.py), [README](https://github.com/hao-ai-lab/Dynasor/blob/0d2f1b93a60e031cfc7fb43843d2b736b225960c/README.md).

**ACER is the closest deadline-aware comparison.** Its public abstract describes changing early-exit thresholds using each request's remaining latency budget. The landing page marks the thesis PDF restricted, and the linked download was not accessible through the browser. No verified official code was located in the targeted search. Its exact forecasting, queue coupling, and threshold-update rules remain unreviewed. We cannot claim cross-request coordination is absent from ACER or reproduce it from the abstract alone. [Official record](https://theses-dissertations.princeton.edu/entities/publication/2d46f9cc-4422-4d22-aa42-2e80ebd5b46f).

**SLAI provides scheduling context, not an equivalent final-answer baseline.** Its abstract describes prioritization around token-delivery deadlines and prefill length. Those TTFT/TBT objectives differ from our correct-final-answer deadline metric. A simple nonpreemptive earliest-deadline-first queue order is a useful local control, but would not be labeled SLAI. [Paper abstract](https://arxiv.org/abs/2508.01002v2).

**Conformal Thinking constrains risk-control claims.** The official summary describes calibrated stopping under a target error risk using validation data. Our small serving campaign has neither implemented that calibration nor established the assumptions needed to inherit a guarantee. [Official summary](https://machinelearning.apple.com/research/conformal-thinking-risk-control).

## Comparison selected for the next implementation stage

The closest-method target is **a paper-based LASER adaptation on the same vLLM runtime**, accompanied by a fixed-threshold probe control and the current admission/live pair. Public Dynasor is a useful source of probing contracts and a secondary comparison candidate; its pinned helper is not ready to use unchanged. ACER remains a required literature gap before a strong deadline-coordination novelty claim.

The proposed 6B work is a bounded CPU/interface investigation, initially one working session. It can establish the following before proposing GPU resources:

| Interface or choice | Proposed comparison contract |
| --- | --- |
| Initial allocation | LASER's chunk-budget rule, with chunk/token conversion and any safety clipping explicitly recorded |
| Exit decision | Paper threshold update using its stated load signal; fixed-threshold control uses the same probes |
| Probing | Specify ATP detection, probe prompt, confidence computation, interval, and accounting from primary methods; unresolved details are implementation gates, not invented “faithful” defaults |
| Completion | A successful request includes the final answer, cue if used, transport, and all probes; intermediate correct probes do not count as a completed final |
| Quality calibration | Exposed indices 0–99 only, including calibration costs; no tuning on the 5A cohort |
| Caching | A matched cache-enabled campaign if probes need caching; rerun all compared policies under it rather than comparing against the old cache-disabled measurements |
| Load variants | Stated active-count version first; any active-plus-waiting version is a separately named adaptation and ablation |
| Scheduler | Keep stock scheduling for the policy comparison; EDF is a separate scheduling control, not quietly mixed into one policy |
| Costs | Count probe/prefill/decode tokens, repeated prefix work, cache occupancy, auxiliary calls, CPU scheduling time, allocation and calibration |

The CPU checks should cover inconsistent/empty/uncertain probe windows, exact budget/cue boundaries, phase isolation, caps, cancellation, and request identity across probes. A local correction to the Dynasor helper would be documented alongside its pin and the unmodified CPU result. No upstream issue or message has been sent.

A GPU comparison is proposed only after the probe/ATP definitions and runtime path are reproducible. If the primary algorithm cannot be specified within that session, a clearly labeled progress-aware baseline can still be useful, but it will not be reported as a faithful LASER or Dynasor reproduction. 6C will need a new frozen plan, development-only settings, matched workload, and its own realistic resource ceiling. It does not consume 5A's reserve or its 28-GPU-hour maximum.

## The hypothesis still worth testing

A potential distinction is **choosing an active request and budget revision by estimating which waiting final answers become feasible before their deadlines**. Load adaptation, deadline awareness, answer stability, or a different engine alone are already insufficient claims.

The comparison would need to beat a simple deadline guard as well as current LARB and an appropriate prior-method adaptation. Matching queue pressure alone tests whether deadline information matters; it does not establish value from forecasting downstream benefits. [FEASIBILITY.md](FEASIBILITY.md) proposes stronger controls that keep active-request deadlines fixed and vary waiting-request deadlines, including an equally urgent but unsalvageable workload.

This capability was not explicitly found in the inspected LASER algorithm or described Dynasor controls, but that observation does not clear the wider literature, and ACER's full algorithm remains a material gap. The next contribution decision can be positive, narrower characterization, or a decision to stop without forcing a novelty claim.
