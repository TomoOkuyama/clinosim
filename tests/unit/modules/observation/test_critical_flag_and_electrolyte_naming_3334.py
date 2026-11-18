"""A result at or beyond a critical limit carries the critical flag, and a
hyperkalaemia / hypokalaemia / hypernatraemia value is named in notes even
when not critical (Issue #3334)."""

from __future__ import annotations

import pytest

from clinosim.modules.document.narrative.lab_timeseries import select_notable_labs
from clinosim.modules.observation.engine import determine_flag, panic_side

pytestmark = pytest.mark.unit

ADMIT = "2026-02-24T18:00:00"


@pytest.mark.parametrize("country", ["US", "JP"])
@pytest.mark.parametrize(
    ("lab", "value", "flag"),
    [
        ("K", 6.5, "critical"),  # at the limit (UKKA: severe hyperkalaemia K >= 6.5)
        ("K", 6.7, "critical"),
        ("K", 6.4, "H"),
        ("K", 2.4, "critical"),
        ("Na", 160.0, "critical"),
        ("Glucose", 500.0, "critical"),
    ],
)
def test_high_critical_limit_is_inclusive(country: str, lab: str, value: float, flag: str) -> None:
    assert determine_flag(lab, value, "M", country=country) == flag
    if flag == "critical":
        assert panic_side(lab, value) is not None


def _finding(name: str, value: float, flag: str) -> list[str | None]:
    labs = [{"lab_name": name, "value": value, "flag": flag, "unit": "mmol/L", "datetime": "2026-02-26T06:00:00"}]
    return [p.finding for p in select_notable_labs(labs, ADMIT, 2)]


def test_potassium_named_beyond_cited_thresholds() -> None:
    assert _finding("K", 6.2, "H") == ["hyperkalemia"]
    assert _finding("K", 5.5, "H") == [None]  # at the 5.5 threshold only; named beyond it
    assert _finding("K", 5.6, "H") == ["hyperkalemia"]
    assert _finding("K", 3.2, "L") == ["hypokalemia"]
    assert _finding("K", 3.5, "L") == [None]
    assert _finding("Na", 148.0, "H") == ["hypernatremia"]
    assert _finding("Na", 145.0, "H") == [None]
