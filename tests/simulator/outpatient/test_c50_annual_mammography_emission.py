"""Phase 4e — C50 breast-cancer follow-up visits emit annual mammography.

Extension of the Phase 4d chronic_followup `procedures:` schema with an
`annual` frequency semantics (fires at most once per calendar year per
patient per procedure). Pilots on C50 mammography (CPT 77067 / SNOMED
71651007) — pattern then available for horizontal extension to
C34 chest CT, C18 colonoscopy, C16 EGD, C22 abdominal US.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile


def _make_c50_patient():
    return PatientProfile(
        patient_id="POP-C50-001",
        sex="F",
        age=58,
        date_of_birth=date(1966, 3, 1),
    )


@pytest.fixture
def c50_fu_spec():
    return load_chronic_followup().get("C50")


def _visit(patient, visit_date, c50_fu_spec, rng_seed=0):
    return _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=visit_date,
        roster=StaffRoster(),
        rng=np.random.default_rng(rng_seed),
        chronic_code="C50",
        followup_spec=c50_fu_spec,
        country="US",
    )


def test_c50_first_visit_in_year_emits_mammography(c50_fu_spec):
    """A C50 patient's first follow-up in a calendar year emits one
    mammography ProcedureRecord (CPT 77067)."""
    assert c50_fu_spec, "C50 block missing"
    patient = _make_c50_patient()
    rec = _visit(patient, datetime(2024, 3, 15, 10, 0), c50_fu_spec)
    codes = {p.procedure_code for p in rec.procedures}
    assert "77067" in codes


def test_c50_second_visit_same_year_does_not_re_emit_mammography(c50_fu_spec):
    """Mammography is annual, not every-visit. A second visit in the same
    calendar year must NOT re-emit CPT 77067."""
    assert c50_fu_spec, "C50 block missing"
    patient = _make_c50_patient()
    _visit(patient, datetime(2024, 3, 15, 10, 0), c50_fu_spec)
    rec2 = _visit(patient, datetime(2024, 6, 15, 10, 0), c50_fu_spec, rng_seed=1)
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert "77067" not in codes2


def test_c50_next_year_visit_re_emits_mammography(c50_fu_spec):
    """A visit in a new calendar year emits a fresh mammography."""
    assert c50_fu_spec, "C50 block missing"
    patient = _make_c50_patient()
    _visit(patient, datetime(2024, 12, 15, 10, 0), c50_fu_spec)
    rec2 = _visit(patient, datetime(2025, 1, 15, 10, 0), c50_fu_spec, rng_seed=1)
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert "77067" in codes2


def test_c50_mammography_procedure_fields_populated(c50_fu_spec):
    """Mammography ProcedureRecord carries CPT code + name_en in
    procedure_type. The yaml ``snomed:`` + ``name_ja:`` fields are
    plumbed through but surface only at FHIR emit (Phase 4d.1)."""
    assert c50_fu_spec, "C50 block missing"
    patient = _make_c50_patient()
    rec = _visit(patient, datetime(2024, 3, 15, 10, 0), c50_fu_spec)
    mammo = [p for p in rec.procedures if p.procedure_code == "77067"]
    assert len(mammo) == 1
    assert mammo[0].procedure_type == "Mammography"
    assert mammo[0].procedure_code_us == "77067"


def test_non_c50_patient_unaffected_by_annual_mammography(c50_fu_spec):
    """Non-regression — a non-C50 chronic followup (I10) does not
    accidentally pick up mammography through the annual-frequency path."""
    htn_spec = load_chronic_followup().get("I10")
    assert htn_spec, "I10 block missing"
    patient = PatientProfile(
        patient_id="POP-HTN-001",
        sex="M",
        age=60,
        date_of_birth=date(1964, 1, 1),
    )
    rec = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 3, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="I10",
        followup_spec=htn_spec,
        country="US",
    )
    codes = {p.procedure_code for p in rec.procedures}
    assert "77067" not in codes
