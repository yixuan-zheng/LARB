"""Width schedules and the generate() hook that applies them.

A step is one forward pass. Step 0 is the prefill (reads the prompt, emits the
first generated position); step k >= 1 reads generated position k-1 and emits
position k. A schedule maps step -> preset name. The KV cache is always kept,
so after a switch the earlier positions keep the history computed at the old width.
"""
from transformers import LogitsProcessor

from common import select

SWITCH_AT = 64

SCHEDULES = {
    "static_L": lambda step: "large",
    "static_S": lambda step: "small",
    "LS_early": lambda step: "large" if step == 0 else "small",
    "LS_late": lambda step: "large" if step < SWITCH_AT else "small",
    "SL_early": lambda step: "small" if step == 0 else "large",
    "SL_late": lambda step: "small" if step < SWITCH_AT else "large",
    "alt16": lambda step: "large" if step // 16 % 2 == 0 else "small",
    "alt4": lambda step: "large" if step // 4 % 2 == 0 else "small",
}


class WidthScheduleProcessor(LogitsProcessor):
    """generate() calls this between forward passes, so we use it to set the next step's width.

    history[k] is the preset of step k; the last entry never runs, so a row with n
    generated positions used history[:n].
    """

    def __init__(self, layers, name, prompt_len):
        self.layers, self.schedule, self.prompt_len = layers, SCHEDULES[name], prompt_len
        self.history = []
        self.set_step(0)

    def set_step(self, step):
        preset = self.schedule(step)
        select(self.layers, preset)
        self.history.append(preset)

    def __call__(self, input_ids, scores):
        # input_ids does not contain the token chosen from `scores` yet, hence + 1
        self.set_step(input_ids.shape[1] - self.prompt_len + 1)
        return scores


def run_lengths(history):
    """['large', 'small', 'small'] -> [['large', 1], ['small', 2]]"""
    runs = []
    for preset in history:
        if runs and runs[-1][0] == preset:
            runs[-1][1] += 1
        else:
            runs.append([preset, 1])
    return runs
