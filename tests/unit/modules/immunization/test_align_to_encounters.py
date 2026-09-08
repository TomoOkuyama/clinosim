"""CIF-layer immunization → encounter alignment — Issue #1197 verify.

Verifies the `_align_to_encounters` post-generation pass that snaps
each immunization's `occurrence_date` to a nearby pediatric_visit
encounter and stamps `encounter_id`. This bridges the calendar
mismatch that made the FHIR emit-time keyword match find only
~4/1969 same-day pairs in the p=500 verify.
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.immunization.enricher import _align_to_encounters
from clinosim.types.encounter import ImmunizationRecord


def _enc(enc_id: str, adm: datetime, enc_type: str = "outpatient") -> SimpleNamespace:
    return SimpleNamespace(encounter_id=enc_id, admission_datetime=adm, encounter_type=enc_type)


def test_no_encounters_leaves_immunizations_unchanged() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1))
    result = _align_to_encounters([imm], [])
    assert result[0].occurrence_date == date(2026, 8, 1)
    assert result[0].encounter_id == ""


def test_same_day_encounter_binds_id() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1))
    enc = _enc("enc-a", datetime(2026, 8, 1, 10, 0))
    result = _align_to_encounters([imm], [enc])
    assert result[0].occurrence_date == date(2026, 8, 1)
    assert result[0].encounter_id == "enc-a"


def test_within_14_days_snaps_date_and_id() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1))
    # Encounter is 5 days later; snap.
    enc = _enc("enc-b", datetime(2026, 8, 6, 10, 0))
    result = _align_to_encounters([imm], [enc])
    assert result[0].occurrence_date == date(2026, 8, 6)
    assert result[0].encounter_id == "enc-b"


def test_beyond_14_days_leaves_unchanged() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1))
    enc = _enc("enc-far", datetime(2026, 8, 20, 10, 0))  # 19 days
    result = _align_to_encounters([imm], [enc])
    assert result[0].occurrence_date == date(2026, 8, 1)
    assert result[0].encounter_id == ""


def test_nearest_encounter_wins() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 10))
    encs = [
        _enc("enc-far", datetime(2026, 8, 1, 10, 0)),  # −9 days
        _enc("enc-near", datetime(2026, 8, 12, 10, 0)),  # +2 days
        _enc("enc-medium", datetime(2026, 8, 5, 10, 0)),  # −5 days
    ]
    result = _align_to_encounters([imm], encs)
    assert result[0].encounter_id == "enc-near"
    assert result[0].occurrence_date == date(2026, 8, 12)


def test_inpatient_encounters_are_ignored() -> None:
    imm = ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1))
    # Inpatient encounter same day — not a legitimate immunization site.
    enc = _enc("enc-inp", datetime(2026, 8, 1, 10, 0), enc_type="inpatient")
    result = _align_to_encounters([imm], [enc])
    assert result[0].occurrence_date == date(2026, 8, 1)
    assert result[0].encounter_id == ""


def test_multiple_immunizations_all_get_aligned() -> None:
    imms = [
        ImmunizationRecord(vaccine_cvx="140", occurrence_date=date(2026, 8, 1)),
        ImmunizationRecord(vaccine_cvx="141", occurrence_date=date(2026, 9, 15)),
    ]
    encs = [
        _enc("enc-a", datetime(2026, 8, 3, 10, 0)),
        _enc("enc-b", datetime(2026, 9, 16, 10, 0)),
    ]
    result = _align_to_encounters(imms, encs)
    assert result[0].encounter_id == "enc-a"
    assert result[0].occurrence_date == date(2026, 8, 3)
    assert result[1].encounter_id == "enc-b"
    assert result[1].occurrence_date == date(2026, 9, 16)
