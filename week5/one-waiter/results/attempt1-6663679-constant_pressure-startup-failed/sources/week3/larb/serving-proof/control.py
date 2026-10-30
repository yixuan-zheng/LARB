"""Request-local token control, independent of vLLM and CUDA."""
from dataclasses import dataclass


@dataclass
class RequestControl:
    key: str
    output: list
    budget: int
    cue: list
    close_id: int
    eos_id: int
    answer_cap: int = 2048
    scanned: int = 0
    close_index: int | None = None
    force_start: int | None = None
    version: int = 0
    ignored_after_close: bool = False

    def refresh(self):
        for i in range(self.scanned, len(self.output)):
            if self.output[i] == self.close_id and self.close_index is None:
                self.close_index = i
        self.scanned = len(self.output)

    def change(self, budget, version):
        self.refresh()
        if version <= self.version:
            return False
        self.version = version
        if self.close_index is not None or self.force_start is not None:
            self.ignored_after_close = True
            return False
        self.budget = min(self.budget, budget)
        return True

    def next_forced(self):
        self.refresh()
        # Finish the entire cue, including its trailing whitespace.
        if self.force_start is not None:
            offset = len(self.output) - self.force_start
            if offset < len(self.cue):
                return self.cue[offset]
        if self.close_index is not None:
            if len(self.output) - self.close_index - 1 >= self.answer_cap:
                return self.eos_id
            return None
        if len(self.output) >= self.budget:
            self.force_start = len(self.output)
            return self.cue[0]
        return None


def move_rows(rows, moves):
    """Apply vLLM's ordered row moves; state follows the request, not the row."""
    for source, target, swap in moves:
        if swap:
            left, right = rows.pop(source, None), rows.pop(target, None)
            if right is not None:
                rows[source] = right
            if left is not None:
                rows[target] = left
        else:
            value = rows.pop(source, None)
            rows.pop(target, None)
            if value is not None:
                rows[target] = value
