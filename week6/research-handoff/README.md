# LARB Week 6 research handoff

This package covers the work after the [Week 6 admission-timing audit](../admission-timing-audit/DECISION.md). The objective is still to improve correct-on-time goodput while preserving answer correctness and reducing wasted reasoning. The later shared-prefix experiments measured isolated correctness and token costs. Their results inform that serving objective, which still needs concurrent validation.

| Work | Result | Decision |
|---|---|---|
| Engine-entry pilot, H100 job 6827065 | Both gates passed and all 72 measured responses and 14 probes completed. Arrival-only, entry-only and live produced 6, 7 and 7 correct-on-time answers out of 24, with 11, 9 and 9 correct overall. Entry retained 56.7% and 39.9% of live's token savings in the two blocks. | Reject frozen H1. Entry missed the half-savings requirement in block 1 and lost overall correctness against arrival-only. |
| Shared-prefix study, L40S job 6878140 | All 60 instances completed. On 40 evaluation instances, answering at 4K gave 12 correct, continuing to 8K gave 18, and the sealed confidence rule gave 14. Hindsight preserved all 18 at 236,647 tokens versus 346,728 for 8K. | Opportunity passed. Stop the confidence selector, which caught two of six gains and saved 12.4%, below the 15% requirement. |
| Signal diagnosis | Across the 57 eligible prefixes, persistent failures generally had lower sampled-token confidence than useful continuations. The association varied by split. Correction phrases, repetition and confidence trends offered weak separation. | Use continuation benefit as the target. Treat the explored questions as development data. |
| Blinded reasoning-state annotation | Two AI readers agreed at κ = 0.886. Their agreed unfinished group contained all eight gains in 28 prefixes, a narrow 2.04× enrichment. They gave the same label to both seeds in all four discordant questions. | The coarse screen passed. Test how much the trajectory adds beyond question identity. |
| Blinded question versus prefix comparison | Gain-ranking AUC rose from 0.635 to 0.930. At 28 extensions, question-only gave 24/57 correct at 413,107 tokens and prefix gave 28/57 at 414,396. Prefix ranked the gaining seed higher in three of four discordant questions. | The frozen branch stopped on the exact realized-cost gate. The 1,289-token excess preceded observation overhead. The grouped accuracy interval was 0 to +15.7 percentage points. |

The two failed shared-prefix attempts are part of the record. Job 6865548 exposed an artificial early-close fixture that produced two closing tokens. Job 6867511 passed the revised fixture and exposed a valid initial opening token rejected by the runner. Job 6878140 passed the corrected gates. The cohort, budget counts and grading were preserved across those engineering corrections.

The last two comparisons used separate outcome-blinded AI readers from the same model family. They establish exploratory evidence on the existing cohort. Human agreement, fresh-question generalization, and the cost of reading a trajectory remain open. The full grid shows a potential allocation advantage at lower extension counts, which should inform a prospective comparison without changing the frozen decision.

The literature review motivated separating three questions. Confidence can help screen candidate trajectories, and answer stability can indicate a useful stopping point. Risk control can account for early exits on both confidently solved and persistently unpromising requests. Load-aware serving and uncertain length scheduling then address the separate cost imposed on other requests. Our contribution should be measured through the joint outcome of correctness and deadline completion, including the cost of observing a signal. [DeepConf](https://arxiv.org/html/2508.15260) · [Dynasor](https://arxiv.org/html/2412.20993) · [Conformal Thinking](https://arxiv.org/html/2602.03814) · [LASER](https://arxiv.org/html/2606.31580) · [Uncertainty-aware length scheduling](https://arxiv.org/html/2604.00499)

The two follow-up priorities are in the [Week 7 plan](../../week7/README.md).

## Evidence and reproduction

`results.json` collects the measured decisions and comparison grids. `code/` contains the executed study and analysis code. `evidence.tar.gz` preserves raw responses, gates, paired prefixes and suffixes, the two failure records, and sealed reader judgments. The archive retains only the scheduler snapshots needed to reproduce the engine-entry commits and pressure gates. Runtime model paths and reader access paths were removed. Anonymous reader packets are rebuilt byte for byte from the shared evidence, so the archive stores each prefix once per original study record instead of copying it for every reader.

Run from the repository root with Python 3.10 or later.

```sh
python3 -B week6/research-handoff/reproduce.py
```

The command verifies the archive and executed source hashes, runs the CPU tests, reconstructs both queue gates and the frozen H1 decision, audits all shared prefixes, and reproduces the signal and blinded comparison results in a temporary directory. Model revisions, input manifests and original dataset notices are inside the archive. The AIME 2024 sources retain their MathArena attribution and [CC BY-NC-SA 4.0 terms](https://creativecommons.org/licenses/by-nc-sa/4.0/). [AIME I](https://huggingface.co/datasets/MathArena/aime_2024_I) · [AIME II](https://huggingface.co/datasets/MathArena/aime_2024_II)
