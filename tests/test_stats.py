"""Hand-computed fixture for the statistics (ROADMAP.md: one CI method,
clustered standard errors, tested against a worked example)."""

from __future__ import annotations

import math

import pytest

from probo import stats

# Four tasks, three attempts each.
A = {"t1": [1, 1, 1], "t2": [0, 0, 0], "t3": [1, 0, 0], "t4": [0, 1, 1]}
# A second configuration on the same tasks.
B = {"t1": [1, 1, 1], "t2": [1, 0, 0], "t3": [0, 0, 0], "t4": [0, 0, 1]}


def test_pass_rate_hand_computed() -> None:
    # mean = 6 / 12 = 0.5
    # per-task residual sums: 1.5, -1.5, -0.5, 0.5 -> squares sum to 5
    # SE = sqrt(5) / 12
    pr = stats.pass_rate(A)
    assert pr.n_tasks == 4 and pr.n_scores == 12
    assert pr.mean == pytest.approx(0.5)
    assert pr.se == pytest.approx(math.sqrt(5) / 12)
    assert pr.ci_low == pytest.approx(0.5 - stats.Z_95 * math.sqrt(5) / 12)
    assert pr.ci_high == pytest.approx(0.5 + stats.Z_95 * math.sqrt(5) / 12)
    # Equivalent form: standard error of the task means with population variance.
    means = [1, 0, 1 / 3, 2 / 3]
    pop_sd = math.sqrt(sum((m - 0.5) ** 2 for m in means) / 4)
    assert pr.se == pytest.approx(pop_sd / math.sqrt(4))


def test_pass_rate_edge_cases() -> None:
    assert stats.pass_rate({"t": [1, 1]}).se == 0.0
    # Two tasks with means 1 and 0: population sd 0.5 over sqrt(2).
    assert stats.pass_rate({"t": [1], "u": [0]}).se == pytest.approx(0.5 / math.sqrt(2))
    empty = stats.pass_rate({})
    assert empty.n_tasks == 0 and math.isnan(empty.mean)
    # A task with no attempts is ignored, not counted as zero.
    assert stats.pass_rate({"t": [1], "u": []}).n_tasks == 1
    # The interval is clipped to [0, 1].
    assert stats.pass_rate({"t": [1], "u": [1], "v": [0]}).ci_high <= 1.0


def test_paired_difference_hand_computed() -> None:
    # task means A: 1, 0, 1/3, 2/3; B: 1, 1/3, 0, 1/3
    # diffs: 0, -1/3, 1/3, 1/3 -> mean 1/12
    # sample sd = sqrt(0.305556 / 3) = 0.319142; SE = sd / 2
    d = stats.paired_difference(A, B)
    assert d.n_tasks == 4
    assert d.mean == pytest.approx(1 / 12)
    assert d.se == pytest.approx(0.1595713, abs=1e-6)
    assert d.ci_low < 0 < d.ci_high
    assert not d.detectable
    assert d.mdd == pytest.approx((1.959964 + 0.841621) * 0.1595713, abs=1e-5)


def test_paired_difference_detectable_and_edge_cases() -> None:
    big = {"t1": [1, 1], "t2": [1, 1], "t3": [1, 0], "t4": [1, 1]}
    small = {"t1": [0, 0], "t2": [0, 0], "t3": [0, 0], "t4": [0, 1]}
    d = stats.paired_difference(big, small)
    assert d.mean == pytest.approx(0.75)
    assert d.detectable
    assert stats.paired_difference(A, {}).n_tasks == 0
    one = stats.paired_difference({"t1": [1]}, {"t1": [0]})
    assert one.n_tasks == 1 and one.mean == 1.0 and math.isnan(one.se)
    # Only shared tasks count.
    assert stats.paired_difference(A, {"t1": [0], "zz": [1]}).n_tasks == 1


def test_consistency_histogram() -> None:
    assert stats.consistency_histogram(A) == {0: 1, 1: 1, 2: 1, 3: 1}
    assert stats.consistency_histogram({}) == {0: 0}


def test_mdd_single_is_conservative_sqrt2() -> None:
    pr = stats.pass_rate(A)
    assert pr.mdd_single == pytest.approx((stats.Z_95 + stats.Z_POWER_80) * math.sqrt(2) * pr.se)


def test_cost_per_resolved_and_median() -> None:
    cpr, missing = stats.cost_per_resolved([1.0, None, 3.0], [True, True, False])
    assert cpr == pytest.approx(2.0) and missing == 1
    assert stats.cost_per_resolved([1.0], [False]) == (None, 0)
    assert stats.median([3, 1, 2]) == 2
    assert stats.median([]) is None
