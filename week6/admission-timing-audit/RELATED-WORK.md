# Focused method comparison — November 4, 2026

This is a method-level comparison, not a benchmark reproduction or exhaustive novelty search. Only author papers/repositories support the comparisons. No external software was installed.

| Work | Decision and quality information | Serving/evaluation setting | Relevance to this audit |
|---|---|---|---|
| LASER | Prompt-length/load budgets plus confidence-based exit at reasoning checkpoints | RTX 4090 sample profiles and FIFO discrete-event serving simulation | Similar joint goal; does not establish our controller's concurrent outcome behavior |
| PASCAL | Reasoning/answering priorities, pacing and phase-boundary migration | Profile-validated cluster simulation; TTFT and answer-stream SLOs | Separates phase handling from final-answer deadline correctness |
| Dynasor/Certaindex | Probed answer stability and program-aware allocation/scheduling | Reasoning programs; paper implementation in SGLang, public vLLM-facing tooling | Stronger progress signal than our queue-count rule; extra probe/cache behavior needs fair accounting |

**LASER.** The method updates a load-smoothed exit threshold and assigns budgets from prompt length and load. Its system evaluation profiles samples before FIFO simulation, rather than executing our live two-request intervention process. This supports an evaluation distinction, not evidence of a defect or our superiority. Reproduction would require intermediate trial answers/confidences absent from our logs. Its optimization trades accuracy against normalized latency; our main numerator is their intersection: correct completed answers by deadlines. No author implementation was identified in the paper links and targeted repository search; that is not proof none exists. [Method §§3–5](https://arxiv.org/html/2606.31580v1).

**PASCAL.** It prioritizes reasoning, manages answering with pacing, and can migrate requests at phase boundaries. Evaluation uses a profile-validated simulator; its main quality-of-experience targets concern first answering tokens and stream pacing. Our workload has zero observed preemptions and an explicit two-sequence cap, so it does not establish a memory-pressure result comparable to PASCAL. No author implementation was identified in the inspected links/search. [Method/evaluation §§IV–V](https://arxiv.org/html/2602.11530v1).

**Dynasor.** It uses intermediate answer stability to guide computation and coordinates requests within reasoning programs. The paper describes SGLang integration; the current public repository supplies vLLM-facing interfaces and recommends prefix caching for probing. Our frozen engine has prefix caching off and records no intermediate answer probes, so we cannot reconstruct its policy from these artifacts or assume its overhead. The repository is available; compatibility with our pinned stack has not been tested. [Paper §§2–4, Appendix D](https://arxiv.org/html/2412.20993v2), [author repository](https://github.com/hao-ai-lab/Dynasor).

## What this permits us to claim

Related mechanisms already exist. A defensible LARB contribution could identify a serving-stage coordination limitation, remove unnecessary interventions, or characterize a reproducible correctness/goodput boundary. The CPU audit establishes no superiority over these systems. Before a broad comparison, match model, task selection, budgets, confidence/probe cost, arrival process, hardware and deadline definition; disclose unavoidable implementation differences. Do not compare our percentages directly with their headline percentages.

## Connection to existing project work

The Week 5 Builder validated queue-triggered budget changes on an easy cohort. The Explorer supplied a CPU deadline-rescue rule and timing profiles. The corrected FIFO heap reuse is necessary but remains a fixed-lane approximation. Our harder AIME screen established a quality/cost gap; the live-vs-arrival follow-up exposes end-to-end interactions when quality matters. This audit reuses their mechanical evidence and corrected scheduling logic without treating old easy-task timing constants as valid for the new workload.
