# Direct reference extraction

This version uses the pinned upstream helper independently at each checkpoint with archived prompt and prefix IDs. It keeps only final-position logits. Compare against the normalized decoder output at identical lengths and masks using the same frozen 2% relative L2 and 0.999 cosine criteria. Do not use the previous full-sequence slicing path. Keep the last-token 4K control.

Use the same three length-spanning trajectories as the earlier gate. Measure per-checkpoint wall time and peak reserved device memory. Require finite, nonzero representations and full gate coverage. The gate projects the remaining workload from the slowest observed trajectory per scope, reserves two minutes inside a 3,400-second internal budget, and caps projected bulk work at 40 minutes. If the full curve fits, extract all positions. If only prompt and 4K fit, extract those and the 4K single-token control. Stop on parity or memory failure or if core scope exceeds the time budget. Reuse the gate features. Report the actual scope. One L40S, one hour.

The parent frozen protocol governs labels, five question-disjoint folds, PCA and logistic regression, metrics and bootstrap. In reduced scope report only the 4K primary contrast. No continuation-benefit fit.
