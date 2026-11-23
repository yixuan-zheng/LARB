"""Portable policy inputs. Runtime cut eligibility stays in the engine."""
import hashlib
import random
from collections import defaultdict

MODES = (0, 2048, 8192)
PRESSURE_CAP = 4096


def coin_mode(request_id, seed):
    """Stable per-original-request draw. Use the same ID on retries."""
    value = int.from_bytes(hashlib.sha256(f"{seed}:{request_id}".encode()).digest()[:8], "big")
    return 2 if value < (2 * (1 << 64)) // 5 else 1


def shuffle_modes(routes, sources, seed):
    """Offline ablation, preserving mode counts in each source."""
    groups = defaultdict(list)
    for request, source in sources.items():
        groups[source].append(request)
    rng = random.Random(seed)
    out = {}
    for source in sorted(groups):
        ids = sorted(groups[source])
        modes = [routes[key] for key in ids]
        rng.shuffle(modes)
        out.update(zip(ids, modes, strict=True))
    return out


def admission(policy, pressure, *, cached_mode=None, request_id=None, seed=151):
    if policy in {"fixed4k", "fixed8k", "load"}:
        mode = 2
    elif policy in {"task", "combined", "shuffle-load"} and cached_mode in (0, 1, 2):
        mode = cached_mode
    elif policy in {"coin", "coin-load"} and request_id:
        mode = coin_mode(request_id, seed)
    else:
        raise ValueError("Unknown policy or missing route input")
    live = policy in {"load", "combined", "shuffle-load", "coin-load"}
    cap = MODES[mode]
    if policy == "fixed4k" or (live and pressure and mode == 2):
        cap = PRESSURE_CAP
    return mode, cap, live
