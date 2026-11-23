"""Shared pure admission mapping for the cached task/load intervention."""
ARMS = ("fixed8k", "fixed4k", "task", "load", "combined", "shuffle-load")


def choose(arm, question, pressure):
    live = arm in ("load", "combined", "shuffle-load")
    if arm == "shuffle-load":
        mode = question["shuffle_mode"]
    elif arm in ("task", "combined"):
        mode = question["selected"]
    else:
        mode = 2
    cap = (0, 2048, 8192)[mode]
    if arm == "fixed4k" or (live and pressure and mode == 2):
        cap = 4096
    return mode, cap, live


def prefixes(tokenizer, problem):
    from probe import mode_ids, template_parts
    root, think, direct = template_parts(tokenizer, problem, routed=True)
    if tokenizer.convert_tokens_to_ids("<think>") not in think:
        think += tokenizer.encode("<think>\n", add_special_tokens=False)
    ids = list(mode_ids(tokenizer).values())
    return [root + [label] + bridge for label, bridge in zip(ids, (direct,think,think),strict=True)]
