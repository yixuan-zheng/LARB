# Final policy contract

Every scored arm uses Qwen3-4B plus the same step-24 LoRA, the same question prompt and boxed integer grader, and one final answer with a 2,048-token answer allowance. The live reference uses temperature 0.6, top-p 0.95, top-k 20, and the per-request seed from the frozen trace. It uses a 12,288-token context and a separate 220-second deadline measured from scheduled arrival. A longer administrative drain only determines how long the harness waits for eventual results. Warm-up and calibration do not enter scored comparisons.

The routing prompt ends at the assistant boundary. The next action is one token, digit 1, 2, or 3. Low (1) uses the native empty-thinking prefix and no reasoning. Medium (2) opens reasoning with a 2,048-token ceiling. High (3) opens reasoning with an 8,192-token ceiling. Early natural closure is allowed. Fixed 4K and pressure-reduced High keep the High digit and apply a 4,096-token ceiling. The worker inserts the closure cue when required and preserves the answer allowance. The final coin experiment drew only Medium and High.

| Policy | Initial action | Routing inference | Data needed before replay | Pressure admission | Live cut |
|---|---|---|---|---|---|
| Fixed 4K | High prefix at 4,096 | None | None | No | No |
| Fixed 8K | High at 8,192 | None | None | No | No |
| Task-only | Learned Low/Medium/High | Required to compute route, cached in replay | Question and matching cached route | No | No |
| Load-only | High at 8,192 | None | None | High → 4,096 | Yes |
| Combined | Learned Low/Medium/High | Required to compute route, cached in replay | Question and matching cached route | High → 4,096 | Yes |
| Within-source shuffle + load | Permute cached routes within each source | Required to construct original assignments | Source membership and entire replay roster | High → 4,096 | Yes |
| Probabilistic-only | Medium 0.60, High 0.40 | None | None | No | No |
| Probabilistic + load | Same probabilistic action | None | None | High → 4,096 | Yes |

Combined is the original research proposal. The experiments staged the checkpoint's greedy routing decisions offline and did not charge online router latency or GPU contention. An online implementation can score the three allowed root IDs once and inject the matching bridge into generation. Preserve the tokenizer and route-prompt revision when using cached assignments. Within-source shuffle is an ablation: it preserves the learned mode histogram within each evaluated source and permutes recipients. It cannot be deployed as tested without an evaluation roster and source labels.

The practical coin uses one assignment per request and reuses it on retries. The final replay consumed a seeded Python PRNG in request-arrival order and persisted the draws in its manifest. A production service can use a stable hash of seed and original request ID to make retried or reordered transport deterministic. The hash-based implementation is provided separately and produces a different realized sequence from the archived PRNG. The 40% rate was selected from a 0.1 grid on 24 development questions as the cheapest expected point within five accuracy points of fixed High.

```text
mode = fixed decision | cached learned action | shuffled cached action | stable coin
ceiling = cap[mode]
if load_enabled and waiting_at_arrival >= threshold and mode is High:
    ceiling = 4096
submit(mode_prefix, ceiling, independent_answer_allowance)
if load_enabled and pressure persists for two scheduler steps:
    choose eligible open request with greatest remaining reasoning budget
    cut at most one request per step to 4096 without reopening reasoning
```

The replay threshold is one waiting request. Live eligibility requires a budget above 4,096, at least 512 tokens of progress, and at least 1,024 current budget tokens remaining. A request whose reasoning closed or cue already started is ineligible. Ties use earliest arrival then request key. A cut requested after 4,096 takes effect at the current progress. Record worker cut events and reconcile them before scoring; distinguish a recorded cut from a forced close at the effective cut position. Pressure snapshots and timing fields use the same node's monotonic clock.

[Portable policy logic](policy.py) · [Archived live policy mapping](reference/routed_contract.py) · [HTTP and worker overlays](reference/overlay/) · [Final burst manifest](reference/freeze.json)
