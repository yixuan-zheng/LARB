"""Fixture-only processor that makes the production cap path bind."""

from larb_scaled.controller import PressureProcessor


class BindingProcessor(PressureProcessor):
    def apply(self, logits):
        logits = super().apply(logits)
        for row, state in self.rows.items():
            if state.force_start is None and state.close_index is None:
                logits[row, state.close_id] = -float("inf")
                logits[row, state.eos_id] = -float("inf")
        return logits
