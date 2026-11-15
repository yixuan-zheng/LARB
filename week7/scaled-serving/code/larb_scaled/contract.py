"""Request-local thinking/answer contract, independent of vLLM and CUDA.

The contract preserves the week 3-6 semantics:
- the opening thinking token counts;
- cue tokens count as output tokens but not as thinking tokens;
- the answer allowance starts after the close token;
- a naturally closed thinking phase is never cut;
- a cut is one-way.

The short-boxed contract is a gated variant: the cue itself ends with the
close token and opens a boxed answer, the answer cap is small, and a closing
brace is forced at the cap before EOS.
"""
from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Contract:
    name: str
    cue: List[int]
    close_id: int
    eos_id: int
    answer_cap: int
    closing_brace_id: Optional[int] = None
    force_closing_brace: bool = False
    cue_text: str = ""
    description: str = ""

    def validate(self):
        if not self.cue:
            raise ValueError("cue must not be empty")
        if self.answer_cap < 1:
            raise ValueError("answer_cap must be positive")
        if self.force_closing_brace and self.closing_brace_id is None:
            raise ValueError("short contract requires closing_brace_id")
        if self.close_id not in self.cue:
            raise ValueError("close_id must appear in the cue; this is what starts the answer allowance")
        return self


@dataclass
class RequestControl:
    key: str
    output: list
    budget: int
    cue: List[int]
    close_id: int
    eos_id: int
    answer_cap: int = 2048
    closing_brace_id: Optional[int] = None
    force_closing_brace: bool = False
    contract_name: str = "legacy"
    scanned: int = 0
    close_index: Optional[int] = None
    force_start: Optional[int] = None
    version: int = 0
    ignored_after_close: bool = False
    closing_forced: bool = False
    cut_history: List[dict] = field(default_factory=list)
    arrival_ts: Optional[float] = None

    @classmethod
    def from_contract(cls, key, output, budget, contract, arrival_ts=None):
        contract.validate()
        return cls(key=key, output=output, budget=budget, cue=list(contract.cue),
                   close_id=contract.close_id, eos_id=contract.eos_id,
                   answer_cap=contract.answer_cap, closing_brace_id=contract.closing_brace_id,
                   force_closing_brace=contract.force_closing_brace,
                   contract_name=contract.name, arrival_ts=arrival_ts)

    def refresh(self):
        for i in range(self.scanned, len(self.output)):
            if self.output[i] == self.close_id and self.close_index is None:
                self.close_index = i
        self.scanned = len(self.output)

    def cue_complete(self) -> bool:
        return self.force_start is not None and len(self.output) - self.force_start >= len(self.cue)

    def change(self, budget, version, reason="pressure"):
        """Apply a downward-only budget change before the cue has started."""
        self.refresh()
        if version <= self.version:
            return False
        self.version = version
        if self.close_index is not None or self.force_start is not None:
            self.ignored_after_close = True
            return False
        new_budget = min(self.budget, budget)
        if new_budget >= self.budget:
            return False
        self.cut_history.append(dict(reason=reason, old_budget=self.budget,
                                     new_budget=new_budget, tokens=len(self.output),
                                     version=version))
        self.budget = new_budget
        return True

    def _answer_tokens(self) -> int:
        if self.close_index is None:
            return 0
        return max(0, len(self.output) - self.close_index - 1)

    def next_forced(self) -> Optional[int]:
        """Return the next token the controller must force, or None."""
        self.refresh()
        if self.force_start is not None:
            offset = len(self.output) - self.force_start
            if offset < len(self.cue):
                return self.cue[offset]
            if self.close_index is not None:
                answer = self.output[self.close_index + 1:]
                if self.force_closing_brace and answer and answer[-1] == self.closing_brace_id:
                    return self.eos_id
                if self._answer_tokens() >= self.answer_cap:
                    if self.force_closing_brace and not self.closing_forced:
                        self.closing_forced = True
                        return self.closing_brace_id
                    return self.eos_id
            return None
        if self.close_index is not None:
            if self._answer_tokens() >= self.answer_cap:
                if self.force_closing_brace and not self.closing_forced:
                    self.closing_forced = True
                    return self.closing_brace_id
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
    return rows
