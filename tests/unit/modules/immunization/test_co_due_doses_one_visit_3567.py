"""Issue #3567: doses the engine gave one date go to one visit, inside their window."""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.types.encounter import ImmunizationRecord

DOB = date(2026, 1, 1)
WINDOWS = {"08": {2: (91, 120)}, "116": {2: (91, 150)}}


def _enc(eid: str, day: date) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id=eid, admission_datetime=datetime(day.year, day.month, day.day, 10), encounter_type="outpatient"
    )


def _dose(cvx: str, day: date) -> ImmunizationRecord:
    return ImmunizationRecord(vaccine_cvx=cvx, occurrence_date=day, dose_number=2)


def _on(age_days: int) -> date:
    return date.fromordinal(DOB.toordinal() + age_days)


def test_co_due_doses_land_on_one_visit() -> None:
    a, b = _dose("08", _on(110)), _dose("116", _on(110))
    # Taken alone, each dose would pick a different visit.
    encs = [_enc("e-a", _on(107)), _enc("e-b", _on(112))]
    _align_to_encounters([a, b], encs, dob=DOB, dose_windows=WINDOWS)
    assert a.occurrence_date == b.occurrence_date
    assert a.encounter_id == b.encounter_id != ""


def test_group_stays_together_when_only_one_member_fits_a_visit() -> None:
    a, b = _dose("08", _on(118)), _dose("116", _on(118))
    # Day 121 is outside the hepatitis B window (91-120) but inside rotavirus (91-150).
    _align_to_encounters([a, b], [_enc("e-late", _on(121))], dob=DOB, dose_windows=WINDOWS)
    assert a.occurrence_date == b.occurrence_date == _on(118)
    assert a.encounter_id == b.encounter_id == ""


def test_lone_dose_never_moves_outside_window() -> None:
    a = _dose("08", _on(118))
    _align_to_encounters([a], [_enc("e-late", _on(121))], dob=DOB, dose_windows=WINDOWS)
    assert a.occurrence_date == _on(118)
    assert a.encounter_id == ""
