# Week 5, lane C (Explorer): targeted shortening

Lane C tests whether a deadline-aware cut rule would decide differently from cut-whenever-full (`live_one`) on saved Week 4 records. It needs no GPU and changes nothing under `week4/`. **Start with the [path memo](PATH-MEMO.md).**

| Task | Where |
| --- | --- |
| C2 shadow rule and deadline input | [targeting.py](targeting.py), [records.py](records.py), [estimates.py](estimates.py), [replay.py](replay.py) → [shadow/](shadow) |
| C3 offline discrimination check | [discriminate.py](discriminate.py) → [results/](results) |
| C4 path memo | [PATH-MEMO.md](PATH-MEMO.md) |
| C5 optional pilot | not run: lanes A/B were not both finished, and C3 shows discrimination but no advantage |

## How it works

- `targeting.py`: the rule as pure functions. Cut at most one running request, and only if that gets one of the next two waiters (FIFO) in by its deadline. If several would, cut the one that frees its slot soonest; otherwise do nothing. `cut_all_decision` is the comparison (`threshold=2` is the Week 4 live rule).
- `records.py`: reads a run directory. Deadlines go onto the server clock as `server arrival + D − client injection lag`, so no two clocks are subtracted.
- `estimates.py`: speed 14.7 ms/token with two requests decoding, 9.3 s from cue to finished answer, 37.6 s fixed-2,048 slot time (all from Week 4 records), and remaining thinking from Week 3 Stage 3 lengths.
- `replay.py`: rebuilds each full-server state from the scheduler and worker logs and logs both rules' choices. `<run>.checks.json` confirms the rebuild: on-time flags match the graded rows, and the two-waiter rule reproduces every recorded live cut.
- `discriminate.py`: replays all 8 runs at base and ±25% estimates and writes `discrimination.csv`, `states.csv`, `plausibility.csv` and `sensitivity.csv`.

## Reproduce (CPU, about 30 s, plain Python 3)

```bash
cd week5/explorer
python3 test_targeting.py     # 12 rule tests
python3 estimates.py          # -> estimates.json
python3 discriminate.py       # -> shadow/*.jsonl.gz, shadow/*.checks.json, results/*.csv
```

Each decision point is judged on its recorded state. After a real or hypothetical cut the trajectory would diverge, so this is a decision test, not a policy result.
