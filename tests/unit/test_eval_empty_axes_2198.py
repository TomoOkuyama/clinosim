"""Axes with no applicable checks stay out of the overall score (Issue #2198)."""

from __future__ import annotations

import pytest

from clinosim.eval.engine import EvalAxisResult, EvalCheck, EvalReport, Outcome, Severity

pytestmark = pytest.mark.unit


def _report(*axes: EvalAxisResult) -> EvalReport:
    return EvalReport(cohort_dir="x", generated_at="t", resource_counts={}, axes=list(axes))


def _axis(name: str, *outcomes: Outcome) -> EvalAxisResult:
    checks = [EvalCheck(name=f"c{i}", outcome=o, severity=Severity.MAJOR, message="") for i, o in enumerate(outcomes)]
    return EvalAxisResult(axis=name, country="JP", checks=checks)


def test_empty_axis_is_not_applicable_and_excluded_from_the_mean() -> None:
    empty = _axis("us_core_compliance")
    full = _axis("structural", Outcome.PASS, Outcome.PASS)
    half = _axis("clinical", Outcome.PASS, Outcome.FAIL)
    report = _report(full, half, empty)
    assert not empty.applicable and empty.status == "N/A"
    assert report.overall_score == 75.0  # mean of 100 and 50, the empty axis is left out
    assert report.to_dict()["axes"][2]["applicable"] is False


def test_report_with_no_applicable_axis_scores_zero() -> None:
    assert _report(_axis("a"), _axis("b")).overall_score == 0.0
