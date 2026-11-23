"""Translate flat Chat Completions metadata for LARB's existing fixed-cap controller."""

import re

from larb_scaled.controller import PressureProcessor


class ChatBudgetProcessor(PressureProcessor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fixture_masks = {}

    def apply(self, logits):
        for index, state in self.rows.items():
            if state.key in self.fixture_masks and len(state.output) < state.budget:
                logits[index, self.fixture_masks[state.key]] = float("-inf")
        return super().apply(logits)

    def update_state(self, batch_update):
        if batch_update:
            for _, params, _, _ in batch_update.added:
                arguments = params.extra_args or {}
                budget = arguments.get("reasoning_cap")
                if budget is None:
                    continue
                key = arguments.get("fixture_id")
                close_id = arguments.get("close_id")
                eos_id = arguments.get("eos_id")
                if (
                    budget not in (512, 2048)
                    or not isinstance(key, str)
                    or not re.fullmatch(r"tau--[a-zA-Z0-9_-]+", key)
                    or type(close_id) is not int
                    or type(eos_id) is not int
                    or not 0 <= close_id < 151936
                    or not 0 <= eos_id < 151936
                    or close_id == eos_id
                ):
                    raise ValueError("Invalid Qwen3 compatibility fixture metadata")
                if arguments.get("hold_until_cap") == 1:
                    blocked = [close_id, eos_id, arguments.get("tool_start_id"),
                               arguments.get("early_eos_id")]
                    if not all(type(token) is int and 0 <= token < 151936 for token in blocked):
                        raise ValueError("Invalid stress fixture token IDs")
                    self.fixture_masks[key] = blocked
                params.extra_args = {
                    **arguments,
                    "larb": {
                        "key": key,
                        "policy": "fixed",
                        "budget": budget,
                        "cue": [close_id],
                        "close_id": close_id,
                        "eos_id": eos_id,
                        "answer_cap": 1024,
                        "contract": "tau-chat",
                    },
                }
        super().update_state(batch_update)
