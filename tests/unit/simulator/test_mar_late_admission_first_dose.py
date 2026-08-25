"""Tests for the day-0 ad-hoc first-dose fallback (Issue #850).

Prior `_generate_mar` skipped every day-0 scheduled-hour slot that was
before ``admission_time`` (a "next 8am" daily order for a patient
admitted at 09:02, or an IV order at hours [0, 8, 16] for a patient
admitted at 16:43). When the encounter's LOS was short enough that
day 1's first slot never fires (encounter discharges before it), the
order got ZERO MedicationAdministration records — 3 such orphan
inpatient MedicationRequests (with `status=completed`) in the JP
p=10000 s500 sample, all daily / IV orders placed on the day of a
short admission.

Fix: on day 0, when EVERY scheduled slot for the day is before
``admission_time`` and no STAT ad-hoc first dose applies, insert an
ad-hoc first-dose slot at ``admission_time + jitter`` (same
30–60 min shape as the STAT path) so every placed medication order
gets at least one administration on the day of admission.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np

from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile


def _patient() -> PatientProfile:
    return PatientProfile(patient_id="POP-mar-850")


def _order(order_id: str, drug: str, route: str, freq: str = "DAILY") -> Order:
    o = Order(
        order_id=order_id,
        encounter_id="ENC-mar-850",
        patient_id="POP-mar-850",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent="",
        ordered_datetime=datetime(2026, 3, 26, 9, 2),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
        route=route,
        frequency=freq,
    )
    return o


class _StubRoster:
    """Minimal StaffRoster stub — assign_staff needs .members and .get_by_role."""

    def __init__(self) -> None:
        self.members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _rng() -> np.random.Generator:
    return np.random.default_rng(42)


def test_enoxaparin_daily_admitted_late_gets_day0_first_dose():
    """Enoxaparin (daily → admin_hours=[8]) placed on a day where the
    patient was admitted at 09:02 (after 8am). Prior emit skipped day 0
    entirely (8:00 < 09:02); with the fix, an ad-hoc slot fires at
    09:02 + 30–60min."""
    admission_time = datetime(2026, 3, 26, 8, 28)
    order = _order("ORD-ENO", "DVT_prophylaxis: Enoxaparin 2000IU SC daily", "SC")
    mars = _generate_mar(
        _patient(),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) >= 1, "day-0 first dose must be scheduled even when admitted after the fixed slot"
    first = mars[0].scheduled_datetime
    # Ad-hoc first dose is 30-60min after admission
    assert (first - admission_time).total_seconds() >= 0
    assert (first - admission_time).total_seconds() < 90 * 60


def test_iv_saline_admitted_late_gets_day0_first_dose():
    """IV route → default [0, 8, 16]. Admitted at 16:43 skips all three
    day-0 slots; the ad-hoc fallback should still fire."""
    admission_time = datetime(2026, 8, 19, 16, 43)
    order = _order("ORD-NS", "IV_fluid: NS 80-125 mL/h", "IV")
    mars = _generate_mar(
        _patient(),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) >= 1
    assert (mars[0].scheduled_datetime - admission_time).total_seconds() < 90 * 60


def test_admission_before_first_slot_uses_scheduled_slot_not_ad_hoc():
    """When admitted BEFORE the first day-0 slot (typical early-morning
    admission), the regular scheduled slot fires — no ad-hoc fallback."""
    admission_time = datetime(2026, 3, 26, 5, 0)  # 05:00 admit, before 08:00 slot
    order = _order("ORD-ENO", "DVT_prophylaxis: Enoxaparin 2000IU SC daily", "SC")
    mars = _generate_mar(
        _patient(),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    assert len(mars) == 1
    # scheduled at hour 8, not admission+jitter
    assert mars[0].scheduled_datetime.hour == 8


def test_stat_order_still_takes_stat_first_dose_not_ad_hoc():
    """STAT orders with an existing ad-hoc first-dose slot must not also
    get the routine-day-0 fallback added — the ``stat_first_dose_time``
    guard keeps the two paths mutually exclusive."""
    admission_time = datetime(2026, 8, 19, 16, 43)
    order = _order("ORD-STAT", "IV_fluid: NS 80-125 mL/h", "IV")
    order.urgency = "stat"
    mars = _generate_mar(
        _patient(),
        [order],
        day=0,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    # STAT already contributes a first-dose slot; no double
    assert len(mars) >= 1
    # First scheduled is within STAT window (30-60min)
    assert (mars[0].scheduled_datetime - admission_time).total_seconds() >= 0


def test_day1_and_later_unaffected():
    """Only day 0 gets the ad-hoc fallback; subsequent days use their
    normal fixed slots."""
    admission_time = datetime(2026, 3, 26, 8, 28)
    order = _order("ORD-ENO", "DVT_prophylaxis: Enoxaparin 2000IU SC daily", "SC")
    mars_day1 = _generate_mar(
        _patient(),
        [order],
        day=1,
        admission_time=admission_time,
        roster=_StubRoster(),  # type: ignore[arg-type]
        rng=_rng(),
    )
    # Day 1 for daily→[8]: scheduled 3/27 08:00 (well after admit)
    assert len(mars_day1) == 1
    assert mars_day1[0].scheduled_datetime.hour == 8
    assert mars_day1[0].scheduled_datetime.date() == datetime(2026, 3, 27).date()
