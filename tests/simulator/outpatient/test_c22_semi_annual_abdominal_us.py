"""Phase 4f — `semi_annual` frequency on chronic_followup `procedures:`.

Pilots on C22 liver (HCC) abdominal ultrasound. NCCN v2.2024 HCC §HCC-G
recommends semi-annual surveillance imaging post-dx; Phase 4e horizontal
shipped C22 as `annual` with a note that `semi_annual` was deferred.
This closes that defer.

Semantics: fires at most once per patient per calendar half-year
(Jan-Jun = H1, Jul-Dec = H2). Two visits in the same half-year are
deduped; a visit in a new half-year re-fires.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile

C22_PROC_CODE = "76700"  # Abdominal ultrasound (CPT)


def _c22_patient() -> PatientProfile:
    return PatientProfile(
        patient_id="POP-C22-SEMI-001",
        sex="M",
        age=60,
        date_of_birth=date(1964, 1, 1),
    )


@pytest.fixture
def c22_fu_spec():
    return load_chronic_followup().get("C22")


def _visit(patient, spec, visit_date, rng_seed=0):
    return _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=visit_date,
        roster=StaffRoster(),
        rng=np.random.default_rng(rng_seed),
        chronic_code="C22",
        followup_spec=spec,
        country="US",
    )


def test_c22_first_visit_in_h1_emits_abdominal_us(c22_fu_spec):
    """C22 patient's first follow-up in H1 (Jan-Jun) emits abdominal US."""
    assert c22_fu_spec
    patient = _c22_patient()
    rec = _visit(patient, c22_fu_spec, datetime(2024, 3, 15, 10, 0))
    codes = {p.procedure_code for p in rec.procedures}
    assert C22_PROC_CODE in codes


def test_c22_second_visit_same_half_year_does_not_re_emit(c22_fu_spec):
    """Second visit same H1 (Jan-Jun) must NOT re-emit."""
    assert c22_fu_spec
    patient = _c22_patient()
    _visit(patient, c22_fu_spec, datetime(2024, 2, 15, 10, 0))
    rec2 = _visit(patient, c22_fu_spec, datetime(2024, 5, 15, 10, 0), rng_seed=1)
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert C22_PROC_CODE not in codes2


def test_c22_visit_in_h2_re_emits_after_h1(c22_fu_spec):
    """A visit in H2 (Jul-Dec) of the SAME calendar year re-emits —
    this is the key difference from `annual`."""
    assert c22_fu_spec
    patient = _c22_patient()
    _visit(patient, c22_fu_spec, datetime(2024, 3, 15, 10, 0))  # H1
    rec2 = _visit(patient, c22_fu_spec, datetime(2024, 9, 15, 10, 0), rng_seed=1)  # H2
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert C22_PROC_CODE in codes2


def test_c22_second_visit_same_h2_does_not_re_emit(c22_fu_spec):
    """Within H2 same year, second visit does not re-emit."""
    assert c22_fu_spec
    patient = _c22_patient()
    _visit(patient, c22_fu_spec, datetime(2024, 8, 15, 10, 0))  # H2 fire
    rec2 = _visit(patient, c22_fu_spec, datetime(2024, 11, 15, 10, 0), rng_seed=1)  # H2
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert C22_PROC_CODE not in codes2


def test_c22_visit_in_next_year_h1_re_emits(c22_fu_spec):
    """A visit in H1 of the next calendar year re-emits — fresh half-year."""
    assert c22_fu_spec
    patient = _c22_patient()
    _visit(patient, c22_fu_spec, datetime(2024, 11, 15, 10, 0))  # 2024 H2
    rec2 = _visit(patient, c22_fu_spec, datetime(2025, 2, 15, 10, 0), rng_seed=1)  # 2025 H1
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert C22_PROC_CODE in codes2


def test_annual_frequency_unaffected_by_semi_annual_path(c22_fu_spec):
    """Non-regression — a non-C22 chronic followup (C50 annual mammography)
    is unaffected by the Phase 4f `semi_annual` addition."""
    c50_spec = load_chronic_followup().get("C50")
    assert c50_spec
    patient = PatientProfile(
        patient_id="POP-C50-NR",
        sex="F",
        age=58,
        date_of_birth=date(1966, 1, 1),
    )
    _ = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 3, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="C50",
        followup_spec=c50_spec,
        country="US",
    )
    # Second visit same H1 (same calendar year) — mammography still deduped (annual).
    rec2 = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 5, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        chronic_code="C50",
        followup_spec=c50_spec,
        country="US",
    )
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert "77067" not in codes2
    # Second visit H2 same year — mammography STILL deduped (annual, not semi_annual).
    rec3 = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 9, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(2),
        chronic_code="C50",
        followup_spec=c50_spec,
        country="US",
    )
    codes3 = {p.procedure_code for p in rec3.procedures}
    assert "77067" not in codes3
