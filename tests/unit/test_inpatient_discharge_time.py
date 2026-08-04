"""Regression guards for planned-discharge timing (Issue #468).

The pre-fix bug was silent: `dc_hour` was clamped to [9, 16] to represent a
daytime discharge, but the value was then *added* as an offset to
`admission_time`. Afternoon admissions rolled the discharge past midnight
(e.g. adm 13:56 → dis 00:56 the next day). The clamp and the variable name
both suggested "business hours" and reviewers read them that way, but the
usage did not match. These tests pin the fix's invariants on the extracted
helper so the same class of drift cannot recur silently.
"""

from datetime import datetime, timedelta

import pytest

from clinosim.simulator.inpatient import _planned_discharge_datetime

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("adm_hour", [0, 6, 8, 9, 13, 14, 16, 20, 23])
@pytest.mark.parametrize("dc_hour", [9, 10, 11, 13, 16])
@pytest.mark.parametrize("actual_los", [1, 3, 7, 14, 30])
def test_planned_discharge_hour_equals_dc_hour(adm_hour, dc_hour, actual_los):
    """Whatever the admission hour, the discharge hour must be exactly
    dc_hour — never rolled forward into the next day. This is the invariant
    the pre-fix `admission + timedelta(hours=dc_hour)` formula violated."""
    adm = datetime(2025, 6, 15, adm_hour, 30, 0)
    dis = _planned_discharge_datetime(adm, actual_los, dc_hour)
    assert dis.hour == dc_hour


def test_planned_discharge_preserves_admission_minute():
    """The minute is carried from admission so all patients don't collapse
    onto the same minute. Silently dropping this (e.g. `.replace(hour=..., minute=0)`)
    would produce an unrealistic footprint but no test failure."""
    adm = datetime(2025, 6, 15, 14, 37, 0)
    dis = _planned_discharge_datetime(adm, 7, 11)
    assert dis.minute == 37


def test_planned_discharge_date_is_admission_plus_los_days():
    """Discharge falls on the calendar date `admission_date + actual_los`,
    not before and not after (no accidental off-by-one via hour rollover)."""
    adm = datetime(2025, 6, 15, 22, 45, 0)  # late admission — most likely to roll
    dis = _planned_discharge_datetime(adm, 7, 9)
    assert dis.date() == (adm + timedelta(days=7)).date()


def test_pre_fix_offset_formula_would_roll_past_midnight():
    """Sanity check on the test's premise: the pre-fix formula
    `admission + timedelta(days=los, hours=dc_hour)` rolls a 14:00 admission
    with clamp-range dc_hour past midnight for at least one value. If this
    ever stops being true, the guards above might be trivially satisfied by
    unrelated changes."""
    adm = datetime(2025, 6, 15, 14, 0, 0)
    for dc_hour in range(9, 17):
        pre_fix = adm + timedelta(days=3, hours=dc_hour)
        if pre_fix.hour < 9 or pre_fix.hour > 16:
            return
    pytest.fail("pre-fix formula no longer rolls past business hours — premise broken")
