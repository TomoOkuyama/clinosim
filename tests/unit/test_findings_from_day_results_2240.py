"""Diagnostic findings come from the day's own results (Issue #2240)."""

from __future__ import annotations

import pytest

from clinosim.simulator.daily_loop import _extract_findings
from clinosim.types.encounter import OrderResult

pytestmark = pytest.mark.unit


def test_crp_drawn_with_a_large_panel_is_seen() -> None:
    # A morning draw: CRP first, then a dozen other analytes.
    day = [OrderResult(lab_name="CRP", value=180.0)] + [OrderResult(lab_name=f"X{i}", value=1.0) for i in range(12)]
    assert ("crp_above_100", True) in _extract_findings(day, "sepsis", 2)


def test_no_results_means_no_findings() -> None:
    assert _extract_findings([], "sepsis", 3) == []
