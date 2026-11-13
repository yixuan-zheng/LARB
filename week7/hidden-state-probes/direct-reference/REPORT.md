# Direct-reference correctness replication

PACE job 6998719 completed on November 12, 2026 at 8:29 p.m. Eastern. The one-L40S allocation took 5m 22s. All 36 engineering comparisons passed, with maximum relative L2 error 0.0 and minimum cosine 0.99999988. These comparisons used identical checkpoint lengths and masks. They validate the direct-reference path. Peak reserved GPU memory was 9.48 GiB. The gate's conservative projection for remaining full-scope replay was 21.1 minutes and the run finished in the same allocation. All 115 rows and all planned checkpoints were extracted. The frozen scorer verified the feature archive hash and exact archived input hashes.

| Representation | AUROC | Accuracy | Brier |
|---|---:|---:|---:|
| Prompt only | .673 | 57.4% | .285 |
| Four-token mean at 4 | .661 | 59.1% | .304 |
| Four-token mean at 4,096 | .767 | 70.4% | .243 |
| Last token at 4,096 | .708 | 68.7% | .274 |

Five question-disjoint folds covered 59 question groups and 115 eligible prefixes. The target was correctness of the single archived 8K-policy branch, with 54 successes. The 4K mean improved pooled held-out AUROC by .094 over prompt-only, with a paired question-bootstrap 95% interval of −.051 to +.248. The early 4-token contrast was −.012, with interval −.133 to +.111. These intervals condition on the fitted folds. The descriptive temporal curve varied across checkpoints.

The 4K probe assigned greater than .998 probability to three incorrect outcomes (Week 6 q10-b0, q22-b1 and q26-b1) and less than .006 to three correct outcomes (Week 6 q03-b0 and q28-b0, and Week 7 q22-b0). The class-balanced probe's raw probabilities should be interpreted cautiously.

The observed 4K point estimate makes the representation worth retaining for the planned comparison. Its advantage over prompt-only remains uncertain, and archived 8K correctness is a different target from the incremental value of extending. No continuation-benefit model was fitted.

[Full metrics](results/RESULTS.json) · [Engineering gate](results/job-6998719/engineering-gate.json) · [Frozen protocol](PROTOCOL.md)
