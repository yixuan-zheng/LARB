# Recoverable-step methodology audit

## Sample and findings

I sampled nine responses by SHA-256 order of `method-audit-v1:<case_id>`: three capped responses without a terminal label, both under-cap responses without a terminal label, two STEP, and two READY. Selection used only reader output and token counts. I inspected the question, 512-token window and response first, then inspected earlier checkpoint text under the same opaque ID. The packet exposed no branch outputs, answer keys or outcome joins. This is a single-reviewer retrospective audit with prior knowledge of aggregate results. The stratified sample describes failure modes.

| Case | Observation |
|---|---|
| 037 | The cap interrupted the response after repeated evidence and an elementary angle calculation. The visible window already contained the polygon closure equation. The generated calculation did not connect the side and diagonal sums to the requested perimeter. |
| 025 | The cap left the decision unfinished. The response repeated algebra visible in the window. Earlier text supplied the 125:6 perimeter equation linking that algebra to the task, a concrete example of context lost at the window boundary. |
| 020 | The response stopped mid-calculation at the cap. The legal moves and a possible dynamic-programming approach were already visible. The response had yet to derive a transition or path count. |
| 068, 035 | Both responses ended below the cap with `READY.` and correctly extracted a candidate already stated and supported in the visible derivation. The period alone is enough to defeat the exact terminal-label check. |
| 044 | Parsed as STEP. The window already had the equation for the next palindrome length. The response identified the obligation to handle other lengths and performed no step toward that count. |
| 059 | Parsed as STEP. The response repeated a subtraction already in the excerpt and left the count it depended on unchecked. |
| 019 | Parsed as READY at the cap. The window supported the terminal multiplication and reduction. The earlier trace held the prime-factorization setup needed to assess that the residue count covered the original divisor problem. |
| 055 | Parsed as READY. The visible window gave the valid differences and completed the requested sum. |

Across all 58 responses, 40 reached the cap without an exact terminal label, two ended below the cap without one, five reached the cap with a valid label, and 11 ended below the cap with a valid label. Cap exhaustion and formatting are separate from mathematical adequacy. The pre-join audit found no material advance among all five parsed STEP calls. This sample finds missing context, output truncation, format-only failures and reasoning failures with relevant information visible. Their population shares and the benefit of an ideal step verifier are unidentified. The actual policy trailed question-only even when its observation cost was set to zero.

## What the papers measure

- [Dynasor/Certaindex, §§2.1 and 3](https://arxiv.org/html/2412.20993) samples immediate answers at successive points on the same reasoning trajectory, discards the probe branches, and measures agreement over a sliding window. Its CoT method also filters uncertain probe responses. It measures answer convergence, which can occur for wrong answers. The LARB step reader saw a single text slice and attempted a local operation. The 4K and 8K final answers are evaluation outcomes and cannot both be observed by a decision made at 4K.
- [Let's Verify Step by Step](https://arxiv.org/html/2305.20050) trains a process reward model from human judgments of existing solution steps and evaluates candidate selection. [Math-Shepherd](https://arxiv.org/html/2312.08935) derives step labels from multiple sampled continuations graded against the reference, then trains a verifier. Our reader proposed a step in one prompt, with a quote-presence check and a small human audit. It had neither trained step supervision nor a continuation-based estimate of step quality. Even a correct step could leave many difficult requirements or leave the answer already obtainable at 4K.

## Next hypothesis

Agreement across three immediate-answer probes by the served model before and at 4K identifies low marginal value from 4K→8K, enough to improve net correctness at matched charged cost. Prefer this to another step prompt because the measurement is directly defined on the trajectory and has a simple output contract.

An outcome-free inventory used a fixed regex for explicit 1–3 digit answer claims or boxed integers in the last 512 tokens before checkpoints 3,072, 3,584 and 4,096. A checkpoint counted only if one distinct candidate was found. Coverage was 2/58, 3/58 and 5/58 respectively. Two traces had candidates at two or more checkpoints and zero had candidates at all three. This passive proxy supplies too few observations to test stability.

If proceeding, use existing saved token IDs for a local replay feasibility test, with the available quantized Qwen3-4B clearly labeled as a proxy for the BF16 generator. At 3,072, 3,584 and 4,096, fork the exact stored token IDs and use one identical immediate-integer prompt with a fixed decode rule and 32-token cap. Discard the probes. Rank complete disagreements above complete agreement, retain question-only rank within groups, and give missing probes the question-only priority between those groups. Freeze all settings before joining outcomes. Report probe validity, stable-wrong and stable-gain cases, wrong-to-right gains and right-to-wrong losses at the common cost ceiling. Charge all three probes and any question-only call used in ranking. The probe decode maximum is 96 tokens per request. Independent forks re-prefill 10,752 saved reasoning tokens plus three copies of the question and cues, so measure prefill, decode and wall time separately. Cache reuse could reduce that cost and needs measurement before assigning savings.

Stop if fewer than 80% of eligible requests produce three parseable answers, if the agreement ranking adds no correct answers over question-only even with zero probe charge, or if it misses a two-correct-answer advantage at the declared charged ceiling. These proposed thresholds are engineering screen criteria. Treat any positive retrospective result as feasibility evidence. A new GPU run would require plausible measured overhead and a frozen question-disjoint evaluation on the pinned BF16 generator.

Only existing traces were inspected. No reader inference or cluster work was launched.
