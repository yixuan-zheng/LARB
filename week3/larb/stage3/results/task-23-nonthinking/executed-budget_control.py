"""Per-request state for a hard thinking boundary; no model dependencies."""
from dataclasses import dataclass


@dataclass
class BudgetState:
    budget: int
    answer_cap: int
    close_id: int
    open_id: int
    count: int = 0
    close_index: int | None = None
    reopened: bool = False

    def __post_init__(self):
        if self.budget < 1 or self.answer_cap < 1:
            raise ValueError('budget and answer_cap must be positive')

    @property
    def should_force(self):
        return self.close_index is None and self.count >= self.budget

    @property
    def answer_tokens(self):
        return 0 if self.close_index is None else self.count - self.close_index - 1

    def observe(self, token):
        if self.close_index is None and token == self.close_id:
            self.close_index = self.count
        elif self.close_index is not None and token == self.open_id:
            self.reopened = True
        self.count += 1
        return self.close_index is not None and self.answer_tokens >= self.answer_cap
