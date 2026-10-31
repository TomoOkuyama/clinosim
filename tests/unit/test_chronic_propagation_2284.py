"""Only modeled chronic conditions propagate from a discharge diagnosis (Issue #2284)."""

from __future__ import annotations

import pytest

from clinosim.simulator.helpers import chronic_code_from_discharge

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "dx",
    ["I21.4", "I26.9", "I61.9", "I63.9", "I80.2", "I82.4", "I49.9", "I66.9", "M80.08", "M84.4", "Z37.0"],
)
def test_acute_discharge_diagnoses_do_not_become_chronic(dx: str) -> None:
    assert chronic_code_from_discharge(dx, "M") is None


@pytest.mark.parametrize(
    ("dx", "chronic"),
    [("I50.9", "I50"), ("I48.91", "I48"), ("J44.1", "J44"), ("E11.65", "E11"), ("K70.30", "K70"), ("K74.60", "K74")],
)
def test_modeled_chronic_conditions_still_propagate(dx: str, chronic: str) -> None:
    assert chronic_code_from_discharge(dx, "M") == chronic


def test_sex_locked_codes_do_not_propagate_for_the_wrong_sex() -> None:
    assert chronic_code_from_discharge("N40.0", "F") is None
    assert chronic_code_from_discharge("N40.0", "M") == "N40"
