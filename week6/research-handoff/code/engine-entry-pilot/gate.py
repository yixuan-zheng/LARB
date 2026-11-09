"""Verify engine-entry commits against raw outputs and causal scheduler snapshots."""
import json

from analyze import completion
from queue_policy import entry_budget


def probe_plan(spec, ids):
    scenarios = [
        ("probe-entry", ids[:3], [0, 0, 0]),
        ("probe-running", ids[:3], [0, 0, 5]),
        ("probe-recovery", ids[3:], [0]),
    ]
    return [
        dict(name=name, policy="entry", role="probe", horizon_seconds=1200,
             arrivals=[dict(slot=i, id=q, seed=spec["request_seed_base"] + q,
                            offset_seconds=offset, relative_deadline_seconds=1200)
                       for i, (q, offset) in enumerate(zip(questions, offsets))])
        for name, questions, offsets in scenarios
    ]


def events(path):
    with path.open() as stream:
        for line in stream:
            yield json.loads(line)


def audit_entry(root, prefix):
    commits = {}
    cues = {}
    admitted = {}
    for event in events(root / "worker.jsonl"):
        key = event.get("key", "")
        if not key.startswith(prefix):
            continue
        if event["event"] == "live_reduction":
            raise ValueError(f"Entry-only live cut: {key}")
        if event["event"] == "admitted":
            admitted.setdefault(key, event)
        if event["event"] == "entry_commit":
            if key in commits:
                raise ValueError(f"Duplicate commit: {key}")
            commits[key] = event
        if event["event"] == "cue_started":
            cues[key] = event

    steps = {event["pressure_step"] for event in commits.values()}
    snapshots = {s["step"]: s for s in events(root / "scheduler.jsonl") if s["step"] in steps}
    records = {}
    for key, commit in commits.items():
        raw = json.loads((root / "requests" / f"{key}.json").read_text())
        snapshot = snapshots[commit["pressure_step"]]
        waiting = [k for k in snapshot["waiting"] if k.split("--")[0] == key.split("--")[0]]
        assert waiting == commit["waiting"] and snapshot["monotonic"] <= commit["monotonic"], key
        assert any(row["key"] == key for row in snapshot["active"]), key
        assert admitted[key]["monotonic"] <= commit["monotonic"], key
        assert raw["initial_budget"] == commit["provisional"] == admitted[key]["initial_budget"], key
        assert commit["budget"] == entry_budget(commit["provisional"], len(waiting), commit["tokens"]), key
        cue = cues.get(key)
        result = completion(raw, cue["tokens"] if cue else None)
        assert raw["complete"] and not raw["error"] and result["reason"] in ("normal", "answer_cap"), key
        assert len(raw["token_ids"]) - result["close_index"] - 1 <= 2049, key
        if cue:
            assert cue["tokens"] == cue["budget"] == commit["budget"], key
        else:
            assert result["close_index"] < commit["budget"], key
        records[key] = dict(commit, finish=raw["finished"], prompt_tokens=len(raw["prompt_token_ids"]),
                            capped=not result["normal"])
    return records


def verify(root):
    records = audit_entry(root, "probe-")
    assert len(records) == 7
    assert any(k.startswith("probe-entry--") and r["provisional"] == 8192
               and r["budget"] == 4096 for k, r in records.items()), "No queued 8K-to-4K entry commit"
    protected = {f"probe-running--r{i:02}": records[f"probe-running--r{i:02}"] for i in range(2)}
    assert all(r["budget"] == 8192 and not r["waiting"] for r in protected.values())
    witnessed = False
    for snapshot in events(root / "scheduler.jsonl"):
        if "probe-running--r02" not in snapshot["waiting"]:
            continue
        active = {r["key"]: r for r in snapshot["active"]}
        if all(k in active and active[k]["computed_before"] > r["prompt_tokens"]
               and r["monotonic"] < snapshot["monotonic"] < r["finish"]
               for k, r in protected.items()):
            witnessed = True
            break
    assert witnessed, "No pressure witnessed while both protected requests were generating"
    recovery = records["probe-recovery--r00"]
    assert recovery["provisional"] == recovery["budget"] == 8192 and not recovery["waiting"]
    return dict(passed=True, records=records, running_pressure_witnessed=True)
