"""Budget references remain stable when a better solution is published."""
import pytest

from engines.python.gold_path import benchmark_budget_length, gold_path_length


def test_legacy_and_empty_levels_keep_their_allowances():
    assert benchmark_budget_length({"solution": {"goldPath": ["right"]}}) == 1
    assert benchmark_budget_length({}) == 0


def test_shorter_solution_changes_scoring_but_not_budget():
    level = {"solution": {"goldPath": ["right"], "benchmarkBudgetLength": 11}}
    assert gold_path_length(level) == 1
    assert benchmark_budget_length(level) == 11


@pytest.mark.parametrize("value", [True, False, 0, -1, 1.5, "11", [], {}])
def test_invalid_budget_is_rejected(value):
    with pytest.raises(ValueError, match="positive integer"):
        benchmark_budget_length({"solution": {"benchmarkBudgetLength": value}})
