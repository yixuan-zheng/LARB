"""Reconcile final request records with the worker's actual cut events."""
import json


def reconcile(raw, keys, path):
    keys = set(keys)
    events = {key: [] for key in keys}
    if path.is_file():
        with path.open() as stream:
            for line in stream:
                if not any(key in line for key in keys):
                    continue
                event = json.loads(line)
                key = event.get("key")
                if key in keys and event["event"] == "live_reduction":
                    events[key].append(event)
    summary = {"record_omissions": 0, "binding_cuts": 0}
    for key, logged in events.items():
        request = raw.get(key)
        if request is None:
            continue
        recorded = request.get("cut_events", [])
        worker_pairs = {(event["tokens"],event["budget"]) for event in logged}
        record_pairs = {(event["tokens"],event.get("budget",event.get("new_budget"))) for event in recorded}
        if record_pairs - worker_pairs:
            raise RuntimeError(f"Request cut lacks worker evidence: {key}")
        summary["record_omissions"] += len(worker_pairs-record_pairs)
        request["cut_events"] = logged
        if logged:
            request["final_budget"] = logged[-1]["budget"]
        cue = request.get("cue_start")
        for event in logged:
            summary["binding_cuts"] += int(cue == max(event["tokens"],event["budget"]))
    return summary
