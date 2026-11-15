"""Small, dependency-free statistics for the serving analysis."""
import math
import random
import statistics

Z_975 = 1.959963984540054
Z_80 = 0.8416212335729143


def wilson_interval(successes, n, z=Z_975):
    if n <= 0:
        return (None, None)
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def paired_mde(n_pairs, discordance, alpha=0.05, power=0.8):
    """80%-power minimum detectable effect for paired binary outcomes, in points."""
    if n_pairs <= 0 or not 0 < discordance <= 1:
        raise ValueError("invalid paired MDE arguments")
    z_alpha = Z_975 if alpha == 0.05 else statistics.NormalDist().inv_cdf(1 - alpha / 2)
    z_power = Z_80 if power == 0.8 else statistics.NormalDist().inv_cdf(power)
    return math.sqrt((z_alpha + z_power) ** 2 * discordance / n_pairs)


def required_pairs(effect, discordance, alpha=0.05, power=0.8):
    if effect <= 0:
        raise ValueError("effect must be positive")
    return math.ceil((paired_mde(1, discordance, alpha, power) / effect) ** 2)


def effective_n(questions, seeds, icc):
    if questions < 1 or seeds < 1 or not 0 <= icc < 1:
        raise ValueError("invalid effective-N arguments")
    return questions * seeds / (1 + (seeds - 1) * icc)


def paired_differences(pairs):
    """pairs: iterable of (arm_a, arm_b) proportions or 0/1 values."""
    diffs = [a - b for a, b in pairs]
    if not diffs:
        return dict(n=0, mean=None, sd=None)
    return dict(n=len(diffs), mean=statistics.mean(diffs),
                sd=statistics.stdev(diffs) if len(diffs) > 1 else 0.0)


def cluster_bootstrap(pairs, resamples=10000, seed=20261113):
    """Bootstrap the mean paired difference by resampling question units."""
    diffs = [a - b for a, b in pairs]
    if not diffs:
        return dict(n=0, mean=None, ci_low=None, ci_high=None, resamples=resamples)
    rng = random.Random(seed)
    means = []
    n = len(diffs)
    for _ in range(resamples):
        sample = [diffs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return dict(n=n, mean=sum(diffs) / n,
                ci_low=means[int(0.025 * (resamples - 1))],
                ci_high=means[int(0.975 * (resamples - 1))],
                resamples=resamples)


def sign_test(diffs):
    """Two-sided exact sign test on non-zero paired differences."""
    positives = sum(1 for d in diffs if d > 0)
    negatives = sum(1 for d in diffs if d < 0)
    n = positives + negatives
    if n == 0:
        return dict(n=0, positives=0, negatives=0, p=1.0)
    # exact two-sided binomial under p=0.5
    def choose(n, k):
        return math.comb(n, k)
    tail = sum(choose(n, k) for k in range(0, min(positives, negatives) + 1)) / (2 ** n)
    return dict(n=n, positives=positives, negatives=negatives, p=min(1.0, 2 * tail))
