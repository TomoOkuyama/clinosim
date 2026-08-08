"""Lock the two MedicationRequest.courseOfTherapyType rules (Issue #548 partial).

`_fhir_medications.py` has two callers that emit `courseOfTherapyType` under
DIFFERENT rules. Named helpers make the divergence explicit at every call
site (see the module docstring for the reasoning). These tests lock:

1. `_course_for_order` — encounter-time orders. Continuous iff home med
   OR category == "community".
2. `_course_for_discharge` — discharge scripts. Continuous iff not a
   discharge (renewal) OR no explicit duration (open-ended maintenance).

The tests also lock the (code, display) tuple constants against silent
drift — the display string `"Continuous long term therapy"` (no hyphen)
is the spec-canonical HL7 form and a re-hyphenation regressed 854 v4
fullset errors historically.
"""

from __future__ import annotations

import pytest

from clinosim.modules.output.fhir_r4.medications.medications import (
    _COURSE_ACUTE,
    _COURSE_CONTINUOUS,
    _course_for_discharge,
    _course_for_order,
)


def test_course_constants_are_spec_canonical() -> None:
    assert _COURSE_CONTINUOUS == ("continuous", "Continuous long term therapy")
    assert _COURSE_ACUTE == ("acute", "Short course (acute) therapy")


@pytest.mark.parametrize(
    "is_home_med,category_code,expected",
    [
        # Home meds are always continuous.
        (True, "inpatient", _COURSE_CONTINUOUS),
        (True, "community", _COURSE_CONTINUOUS),
        (True, "discharge", _COURSE_CONTINUOUS),
        # Community-tagged orders are continuous even if not home meds.
        (False, "community", _COURSE_CONTINUOUS),
        # Everything else defaults to acute.
        (False, "inpatient", _COURSE_ACUTE),
        (False, "discharge", _COURSE_ACUTE),
        (False, "outpatient", _COURSE_ACUTE),
        (False, "", _COURSE_ACUTE),
    ],
)
def test_course_for_order_rule(is_home_med: bool, category_code: str, expected: tuple[str, str]) -> None:
    assert _course_for_order(is_home_med, category_code) == expected


@pytest.mark.parametrize(
    "is_discharge,duration_days,expected",
    [
        # Non-discharge (outpatient renewal): always continuous.
        (False, 7, _COURSE_CONTINUOUS),
        (False, 30, _COURSE_CONTINUOUS),
        (False, None, _COURSE_CONTINUOUS),
        # Discharge with explicit duration: acute.
        (True, 5, _COURSE_ACUTE),
        (True, 14, _COURSE_ACUTE),
        # Discharge with no duration (maintenance handover): continuous.
        (True, None, _COURSE_CONTINUOUS),
    ],
)
def test_course_for_discharge_rule(is_discharge: bool, duration_days: int | None, expected: tuple[str, str]) -> None:
    assert _course_for_discharge(is_discharge, duration_days) == expected


def test_rules_intentionally_diverge_on_shared_input() -> None:
    """A discharge script with duration_days=None goes to continuous under
    `_course_for_discharge` (maintenance handover). An order with the same
    "not a home med, not community" input goes to acute under
    `_course_for_order`. This test locks the intentional divergence so a
    future unification PR (Issue #548 Step 2) knows what to reconcile."""
    # Not a home med, not community → order says acute
    assert _course_for_order(False, "inpatient") == _COURSE_ACUTE
    # Not a discharge → discharge rule says continuous
    assert _course_for_discharge(False, None) == _COURSE_CONTINUOUS
