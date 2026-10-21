# First controlled development comparison

Saved before calibration or measured requests. Run only after real checkpoint
1C validation passes. Earlier smoke outcomes do not choose the policy settings.

## Fixed candidate and workload

Reuse the Week 4 admission/live candidate, Qwen3-4B pinned revision, vLLM 0.11.2,
BF16, two active sequences, unchanged stock scheduling, sampling seeds 6222+i,
16,384 thinking safety cap, 2,048 short budget/answer cap, threshold two waiting,
and the exact Stage 3 transition cue. Same engine, GPU allocation, instrumentation,
sampling, prompts, safety behavior, and trace for every measured policy.

Use exposed MATH-500 development indices 0–11. No reserved questions. Two matched
blocks repeat these same problems and seeds, so there are 12 unique accuracy
examples, not 24 independent examples. Batching can change sampled outputs even
with identical seeds. The second block reverses the first policy order:

1. full, arrival, admission, live
2. live, admission, arrival, full

This balances early/late positions across two blocks; it is not a full Latin
square or an independent randomized replication campaign.

## Calibration rule, fixed before observation

After engine readiness, run two concurrent full-thinking calibration requests,
indices 0 and 2, excluded from measured results. On the client's single monotonic
clock calculate terminal receipt minus scheduled arrival. Set burst offset to
one quarter of the smaller calibration latency, and relative deadline to twice
the larger latency (minimum 30s). Do not tune either after seeing policy outcomes.

Indices 0 and 1 arrive together at zero. Indices 2–11 arrive at burst_offset +
0.05*(i-2) seconds. Write/hash the trace, deadline, observation horizon, calibration
records, and policy orders before starting measured requests. Replay open-loop;
late requests continue to completion within common caps. Check from events that
initial requests had begun generation before the burst.

## Outcomes and decision

Primary: correct, normally completed, client terminal receipt by the deadline,
measured from scheduled arrival on the client clock. Horizon per block/policy:
H = max(offset + deadline). Report counts /12 per block, combined /24 request
outcomes, and correct-on-time counts divided by the same H (2H for both blocks).
The primary comparison is live minus admission, with full and arrival as context.

Thinking/answer caps, errors, cancellations, missing finals, and unfinished
outputs are failures even if an intermediate number is correct. Report eventual
completed correctness separately. Preserve late and failed outcomes. Grade only
the final-answer segment with the existing reviewed boxed extraction and
Math-Verify 0.9.0; separate parser issues from math errors. Any correction needs a
record hash and the same rule across policies. No reference answers enter control.

Report latency, queue delay, thinking/answer tokens, failures, budget reductions,
binding mid-generation cutoffs, controller-event evidence, and allocation cost.
List paired gains/losses and cases explaining admission/live differences.

Continuation screen (diagnostic, not a statistical guarantee): live has more
correct-on-time request outcomes than admission across both blocks, no negative
deadline difference in either block, at least one binding mid-generation cutoff
in each live block, and at most one net eventual-correctness loss vs admission in
each block. Otherwise label the result mixed, negative, or mechanism-inconclusive
and diagnose it; do not automatically tune or rerun for a favorable result.
Do not claim a three-point accuracy guarantee or population benefit. Show the
two block results and the 12 unique problems explicitly as the uncertainty limit.

## Limits and failure handling

One H100 allocation <=90min, driver <=85min, startup <=25min, each phase <=15min.
Two calibration +96 measured requests. No blind automatic retries. Infrastructure
repair is allowed within the saved session's three-GPU-hour ceiling after a
specific diagnosis; retain all attempts and rewrite hashes/settings as needed.
If hardware or engine/policy settings change, rerun complete matched blocks.
If 1C passes, proceed immediately to this comparison; preserve partial results
and active job IDs if interrupted.
