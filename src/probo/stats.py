"""Statistics for pass rates with honest error bars.

Follows Miller, "Adding Error Bars to Evals" (2024): the unit of analysis is
the task, attempts of the same task are correlated, so standard errors are
clustered by task. One confidence-interval method only.

Definitions, with ``s_ij`` the 0/1 score of attempt ``j`` of task ``i``,
``N`` the number of scores and ``n`` the number of tasks:

* pass@1 (averaged over attempts): ``mu = sum(s_ij) / N``.
* clustered standard error: ``SE = sqrt(sum_i (sum_j (s_ij - mu))^2) / N``.
  With equal attempt counts this equals the standard error of the per-task
  means with the population variance.
* 95% interval: ``mu +/- 1.96 SE``.
* paired difference between two configurations on the same tasks: per-task
  mean difference ``d_i``, ``D = mean(d_i)``, ``SE_D = sd(d_i) / sqrt(n)``
  with the sample standard deviation, interval ``D +/- 1.96 SE_D``.
* minimum detectable difference at alpha 0.05 and 80% power:
  ``MDD = (1.96 + 0.84) * SE_D``. Before a second configuration exists the
  single-set MDD is reported with ``SE_D ~= sqrt(2) * SE``, which assumes no
  pairing benefit and is therefore conservative.
"""

from __future__ import annotations

import math
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

Z_95 = 1.959963984540054
Z_POWER_80 = 0.8416212335729143


@dataclass(frozen=True)
class PassRate:
    n_tasks: int
    n_scores: int
    mean: float
    se: float

    @property
    def ci_low(self) -> float:
        return max(0.0, self.mean - Z_95 * self.se)

    @property
    def ci_high(self) -> float:
        return min(1.0, self.mean + Z_95 * self.se)

    @property
    def mdd_single(self) -> float:
        """Conservative minimum detectable difference against a hypothetical
        second configuration on the same tasks (no pairing benefit assumed)."""
        return (Z_95 + Z_POWER_80) * math.sqrt(2.0) * self.se


@dataclass(frozen=True)
class PairedDifference:
    n_tasks: int
    mean: float
    se: float

    @property
    def ci_low(self) -> float:
        return self.mean - Z_95 * self.se

    @property
    def ci_high(self) -> float:
        return self.mean + Z_95 * self.se

    @property
    def mdd(self) -> float:
        return (Z_95 + Z_POWER_80) * self.se

    @property
    def detectable(self) -> bool:
        """True when the interval excludes zero."""
        return self.ci_low > 0 or self.ci_high < 0


ScoresByTask = Mapping[str, Sequence[float]]


def pass_rate(scores_by_task: ScoresByTask) -> PassRate:
    tasks = {t: list(s) for t, s in scores_by_task.items() if len(s) > 0}
    n_scores = sum(len(s) for s in tasks.values())
    if n_scores == 0:
        return PassRate(n_tasks=0, n_scores=0, mean=float("nan"), se=float("nan"))
    mu = sum(sum(s) for s in tasks.values()) / n_scores
    cluster_sq = sum((sum(x - mu for x in s)) ** 2 for s in tasks.values())
    se = math.sqrt(cluster_sq) / n_scores
    return PassRate(n_tasks=len(tasks), n_scores=n_scores, mean=mu, se=se)


def task_means(scores_by_task: ScoresByTask) -> dict[str, float]:
    return {t: sum(s) / len(s) for t, s in scores_by_task.items() if len(s) > 0}


def paired_difference(a: ScoresByTask, b: ScoresByTask) -> PairedDifference:
    """Mean of per-task differences a - b over the tasks present in both."""
    ma, mb = task_means(a), task_means(b)
    common = sorted(set(ma) & set(mb))
    if not common:
        return PairedDifference(n_tasks=0, mean=float("nan"), se=float("nan"))
    diffs = [ma[t] - mb[t] for t in common]
    mean = sum(diffs) / len(diffs)
    if len(diffs) < 2:
        return PairedDifference(n_tasks=1, mean=mean, se=float("nan"))
    se = statistics.stdev(diffs) / math.sqrt(len(diffs))
    return PairedDifference(n_tasks=len(diffs), mean=mean, se=se)


def consistency_histogram(scores_by_task: ScoresByTask) -> dict[int, int]:
    """How many tasks were resolved 0, 1, ..., k of k attempts. Tasks with
    differing attempt counts are binned by their own count."""
    counts = Counter(int(round(sum(s))) for s in scores_by_task.values() if len(s) > 0)
    k = max((len(s) for s in scores_by_task.values()), default=0)
    return {i: counts.get(i, 0) for i in range(k + 1)}


def median(values: Sequence[float]) -> float | None:
    vals = [v for v in values if v is not None and not math.isnan(v)]
    return statistics.median(vals) if vals else None


def cost_per_resolved(costs: Sequence[float | None], resolved: Sequence[bool]) -> tuple[float | None, int]:
    """Total reported cost divided by the number of resolved runs, and how many
    runs had no cost reported (those are excluded from the numerator and the
    result is labelled partial by the caller)."""
    missing = sum(1 for c in costs if c is None)
    total = sum(c for c in costs if c is not None)
    n_res = sum(1 for r in resolved if r)
    if n_res == 0:
        return None, missing
    return total / n_res, missing
