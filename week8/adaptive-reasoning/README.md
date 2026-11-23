# Adaptive reasoning · November 23–25, 2026

My goal is to find out whether Qwen3-4B can learn to choose its own reasoning effort and improve the accuracy–compute trade-off. I’ll close this investigation on Wednesday, November 25, and join the existing AIME serving-scaling effort after the cutoff.

## What I found

- **Reasoning effort mattered on the tested Omni-MATH cohort.** Across 24 questions and two seeds, accuracy rose from 33.3% at 2K to 47.9%, 54.2%, and 60.4% at 4K, 6K, and 8K. Mean output grew from 3,415 to 8,767 tokens, and some answers regressed at higher caps.
- **The earlier selectors gave limited or inconclusive results.** The prompt selector assigned every question 2K. Learned gain scores showed small or inconsistent advantages over short-answer risk and question length. These experiments left open whether a model trained on outcomes could learn to choose its own effort.
- **The agent-task setup works for controlled tool calls.** In the local τ²-bench fixture, Qwen3-4B preserved a structured tool call and handled its result after a binding 2,048-token cap. Customer-simulator fidelity still prevents a reliable full-episode comparison. Whether reasoning effort changes agent task completion remains open.

## What I’ll finish by November 25

**November 23 — Feasibility passed.** The corrected Low/Medium/High fixture produced clean outputs, and all three route tokens received gradients from verified math rewards (PACE job `7254049`). The final binding-cap fixture forced closure at exactly 2,048 and 8,192 reasoning tokens. Both answers graded correctly, and the training replay verified that injected delimiters were excluded from the loss (job `7255384`). These checks establish that the implementation can express and train the actions. Useful learned routing remains untested.

**November 24–25 — One bounded training and evaluation screen, if the allocation is approved and fits the deadline.** Adapt the [three-mode GRPO recipe](https://arxiv.org/html/2608.20256) so Qwen3-4B chooses Low, Medium, or High at the start of generation. Compare free routing on held-out questions with the same checkpoint forced to fixed effort, a compute-matched mixture of fixed modes, and shuffled routing. The target is at least 10% less measured compute at comparable accuracy, with uncertainty reported. Reserve time to finish evaluation and export evidence before committing to the run.

| Result by November 25 | My closeout |
| --- | --- |
| **Positive** | Preserve the checkpoint, recipe, and held-out results. Leave integration as follow-up work. |
| **Inconclusive** | Freeze the prototype and record the effect size, uncertainty, and limitations. |
| **Negative in a valid run** | Record the collapse or lack of allocation gain for this recipe and close the training branch. |
| **Blocked or incomplete** | Preserve the feasibility evidence and mark learned routing unevaluated. |

I’ll stop adaptive-training work at the Wednesday cutoff in all four cases.

## Code and evidence

The [mode fixture results](results/mode-fixture-7254049.json) and [binding-cap fixture results](results/binding-cap-fixture-7255384.json) contain per-case grades, gradient checks, timing, and memory measurements. The package has four fixture-specific files: the rollout probe, training and mask check, binding-cap processor, and Slurm launcher. It reuses the controller, request audit, and grader in [Week 7 scaled serving](../../week7/scaled-serving/code/). The checked-in launcher packages the fixture for reuse from the repository root on PACE. It expects the pinned Qwen3-4B snapshot and vLLM environment under `~/scratch/CS6222-qwen3-baseline`.

```sh
# Corrected modes and native Qwen comparisons
sbatch --export=ALL,LARB_BINDING_FIXTURE=0 week8/adaptive-reasoning/code/run.sbatch
# Force the 2,048- and 8,192-token caps and verify the training mask
sbatch week8/adaptive-reasoning/code/run.sbatch
```

The jobs write detailed records to `~/scratch/larb-adaptive-evidence-<job-id>`. The binding fixture deliberately suppresses early closure while reasoning is open. Use its timings as an engineering measurement, and use naturally generated rollouts to estimate how often caps bind in the workload.
