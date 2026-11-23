# Week 8 | Allocation and serving close-out

| Study | Result |
|---|---|
| **Question-aware allocation replay** | **Complete, stop.** In a CPU replay of the burst trace at 540/h, extending by measured per-question value gave **516** correct-on-time answers versus **545** for a constant value: **−29** (95% interval **−52 to −2**), negative in 10 of 11 sensitivity cells. The values beat a shuffled control by **+62.9**, but extending whenever nobody waits was the better rule. [Report](allocation/REPORT.md) · [Frozen rule](allocation/PROTOCOL.md) |

## Reproduce

Run from the repository root. Only Python 3 is needed.

```sh
python3 -B week8/allocation/test_sim.py
python3 -B week8/allocation/run.py compare   # move results/compare.json aside first
```
