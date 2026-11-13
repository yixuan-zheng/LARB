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

    def state(self, key):
        with self._lock:
            return {"scheduler_start": self.first_active.get(key),
                    "cue": self.cues.get(key),
                    "cuts": list(self.cuts.get(key, [])),
                    "preemptions": self.preemptions.get(key, 0)}


BUS = PressureBus()
_EMIT_LOCK = threading.Lock()


def emit(stream, event, **data):
    OUT.mkdir(parents=True, exist_ok=True)
    row = dict(event=event, monotonic=time.monotonic(), pid=os.getpid(), **data)
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
