"""In-process telemetry bus shared by the vLLM scheduler adapter and server.

This module is pure Python so the CPU tests and the server can import it without
loading vLLM.
"""
import json
import os
import threading
import time
from pathlib import Path

OUT = Path(os.environ.get("LARB_OUT", "."))


class PressureBus:
    def __init__(self):
        self._lock = threading.Lock()
        self.snapshot = {"step": 0, "monotonic": time.monotonic(), "active": [],
                         "waiting": [], "waiting_count": 0, "running_count": 0}
        self.first_active = {}
        self.cues = {}
        self.cuts = {}
        self.caps = {}
        self.preemptions = {}

    def update(self, snapshot):
        with self._lock:
            self.snapshot = dict(snapshot)
            for row in snapshot.get("active", []):
                key = row.get("key")
                if key and key not in self.first_active:
                    self.first_active[key] = snapshot["monotonic"]
                if key is not None and "preemptions" in row:
                    self.preemptions[key] = row["preemptions"]

    def get(self):
        with self._lock:
            return dict(self.snapshot)

    def record_cue(self, key, tokens, monotonic):
        with self._lock:
            self.cues[key] = {"tokens": tokens, "monotonic": monotonic}

    def record_cut(self, key, event):
        with self._lock:
            self.cuts.setdefault(key, []).append(event)

    def record_cap(self, key, reason):
        with self._lock:
            self.caps[key] = reason

    def state(self, key):
        with self._lock:
            return {"scheduler_start": self.first_active.get(key),
                    "cue": self.cues.get(key),
                    "cuts": list(self.cuts.get(key, [])),
                    "cap": self.caps.get(key),
                    "preemptions": self.preemptions.get(key, 0)}

    def write_snapshot(self, snapshot):
        """Persist the queue snapshot so the frontend process can read it.

        vLLM may run the scheduler in a separate engine-core process; the
        in-process bus is then invisible to the HTTP layer. The file is the
        admission-time fallback and the audit trail.
        """
        try:
            atomic(OUT / "pressure.json", snapshot)
        except OSError:
            pass


def read_snapshot(max_age=5.0):
    path = OUT / "pressure.json"
    try:
        value = json.loads(path.read_text())
        age = time.monotonic() - float(value.get("monotonic", 0.0))
    except (OSError, ValueError, TypeError):
        return None
    if age < 0 or age > max_age:
        return None
    return value


BUS = PressureBus()
_EMIT_LOCK = threading.Lock()


def emit(stream, event, **data):
    OUT.mkdir(parents=True, exist_ok=True)
    row = dict(data)
    row["event"] = event
    row["pid"] = os.getpid()
    row.setdefault("monotonic", time.monotonic())
    with _EMIT_LOCK:
        with (OUT / f"{stream}.jsonl").open("a") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(path)


def snapshot_due(step, stride=8):
    return step % max(1, stride) == 0
