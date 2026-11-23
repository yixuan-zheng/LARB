"""Candidate victim ordering, with separate slack and preference controls.

Use after the existing pressure and eligibility rules. Inputs are estimates
available at decision time, never realized remaining service or correctness.
"""
import math


def choose(candidates, *, strategy, bucket_seconds=30):
    if strategy not in ("remaining", "slack", "slack-margin"):
        raise ValueError(strategy)
    if not candidates:
        return None

    def rank(row):
        remaining = row["remaining_budget"]
        slack = row["deadline"] - row["now"] - row["estimated_remaining_seconds"]
        # Prefer requests close to their deadlines. Preserve the original
        # victim order within each slack tier for the slack-only control.
        short_slack = row["deadline"] - row["now"] - row.get("estimated_short_seconds", row["estimated_remaining_seconds"])
        viability = 2 if slack < 0 <= short_slack else 1 if slack >= 0 else 0
        slack_priority = (viability, -math.floor(abs(slack) / bucket_seconds))
        margin = -row["high_minus_medium_logprob"]
        common = (remaining, -row["arrival"], row["key"])
        if strategy == "remaining":
            return common
        if strategy == "slack":
            return (slack_priority, *common)
        return (slack_priority, margin, *common)

    return max(candidates, key=rank)
