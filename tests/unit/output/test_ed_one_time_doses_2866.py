"""One-time doses are one occurrence, not a daily cadence (Issue #2866)."""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.lib.dosage import resolve_timing_repeat

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("label", ["ONCE", "once", "STAT"])
def test_once_and_stat_are_a_single_occurrence(label: str) -> None:
    assert resolve_timing_repeat(label) == ({"count": 1}, False)


def test_daily_is_unchanged() -> None:
    assert resolve_timing_repeat("DAILY") == ({"frequency": 1, "period": 1, "periodUnit": "d"}, False)
