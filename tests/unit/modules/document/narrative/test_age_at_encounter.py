"""Tests for _age_at helper (Issue #1173).

The narrative template layer must quote the patient's age *at the
encounter date*, not the static ``PatientProfile.age`` that was
computed at cohort-generation time. Without this fix, 95.1% of SOAP
progress-note headers under-report age by 1-2 years (birthday not yet
passed within the simulation window or multi-year window drift).
"""

from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import _age_at
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile


def _mk_ctx(dob: date | None, enc_dt: datetime | None, static_age: int = 0) -> NarrativeContext:
    patient = PatientProfile(patient_id="pt-test")
    patient.age = static_age
    if dob is not None:
        patient.date_of_birth = dob
    encounter = SimpleNamespace(encounter_id="enc-test", admission_datetime=enc_dt) if enc_dt else None
    return NarrativeContext(
        patient=patient,
        encounter=encounter,
        encounter_type=None,
        disease_protocol=None,
        encounter_protocol=None,
        clinical_course_archetype="uncomplicated_improvement",
        severity="moderate",
        day_index=0,
        los_days=1,
        vitals=[],
        lab_results=[],
        medications=[],
        diagnoses=[],
        procedures=[],
        allergies=[],
        document_type=DocumentType.OUTPATIENT_SOAP,
        target_lang="ja",
        locale="jp",
    )


def test_birthday_not_yet_passed_this_year_returns_year_diff_minus_one() -> None:
    # Born 2018-06-15, encounter 2026-06-13 → still 7 (birthday next-day)
    ctx = _mk_ctx(dob=date(2018, 6, 15), enc_dt=datetime(2026, 6, 13, 10, 0), static_age=6)
    assert _age_at(ctx) == 7


def test_birthday_already_passed_returns_full_year_diff() -> None:
    # Born 2018-01-06, encounter 2026-06-13 → 8 (birthday passed)
    ctx = _mk_ctx(dob=date(2018, 1, 6), enc_dt=datetime(2026, 6, 13, 10, 0), static_age=6)
    assert _age_at(ctx) == 8


def test_encounter_on_birthday_returns_full_year_diff() -> None:
    # Born 2018-06-13, encounter 2026-06-13 → 8 (birthday today)
    ctx = _mk_ctx(dob=date(2018, 6, 13), enc_dt=datetime(2026, 6, 13, 10, 0), static_age=6)
    assert _age_at(ctx) == 8


def test_missing_date_of_birth_falls_back_to_static_age() -> None:
    ctx = _mk_ctx(dob=None, enc_dt=datetime(2026, 6, 13, 10, 0), static_age=42)
    assert _age_at(ctx) == 42


def test_missing_encounter_falls_back_to_static_age() -> None:
    ctx = _mk_ctx(dob=date(1980, 1, 1), enc_dt=None, static_age=42)
    assert _age_at(ctx) == 42


def test_none_patient_returns_none() -> None:
    ctx = _mk_ctx(dob=date(1980, 1, 1), enc_dt=datetime(2026, 6, 13, 10, 0), static_age=42)
    ctx.patient = None
    assert _age_at(ctx) is None


def test_multi_year_simulation_window_produces_correct_age() -> None:
    # Cohort snapshot at 2025-01-01 records patient.age = 6 (born 2018-04-10).
    # A visit two years into the sim at 2027-08-01 → the patient is now 9.
    # PR A ensures this is 9, not 6, in the narrative header.
    ctx = _mk_ctx(dob=date(2018, 4, 10), enc_dt=datetime(2027, 8, 1, 14, 30), static_age=6)
    assert _age_at(ctx) == 9
