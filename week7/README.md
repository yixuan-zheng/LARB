# Week 7 plan

Review the [Week 6 research handoff](../week6/research-handoff/README.md) for the results behind these two priorities.

- [ ] **Continue prediction research.** Design one bounded observation test against the question-only baseline. Freeze what prefix evidence the reader can use, its compute and latency allowance, and the cost-matched accuracy endpoint. Predict the marginal benefit of continuation, including potential correctness losses. Use protected questions for a generalization claim and group seeds by question. Stop if the observation cost or allocation errors erase the benefit.
- [ ] **Design a more realistic serving environment.** Specify a workload with mixed request lengths and reasoning needs, variable arrivals and bursts, and request-level deadlines. Exercise continuous batching and separate prefill, reasoning and answer timing. Start with trace replay and a small calibration workload. Compare policies on correct answers delivered by their deadlines, overall correctness, actual GPU cost and latency tails, including capped, failed and late requests.
