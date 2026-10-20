"""Phase 4d — OSA follow-up visits emit CPAP + polysomnography procedures.

Direct test of the simulator path that reads chronic_followup.yaml
`procedures:` entries and appends ProcedureRecord to the CIFPatientRecord.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile


def _make_osa_patient():
    return PatientProfile(
        patient_id="POP-OSA-001",
        sex="M",
        age=55,
        date_of_birth=date(1970, 1, 1),
    )


@pytest.fixture
def osa_fu_spec():
    return load_chronic_followup().get("G47.30")


def test_osa_first_followup_emits_cpap_and_polysomnography(osa_fu_spec):
    """Year 1 OSA follow-up — one CPAP + one polysomnography ProcedureRecord."""
    assert osa_fu_spec, "G47.30 block missing"
    patient = _make_osa_patient()
    rec = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 6, 1, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="G47.30",
        followup_spec=osa_fu_spec,
        country="US",
    )
    codes = {p.procedure_code for p in rec.procedures}
    assert "99503" in codes  # CPAP
    assert "95810" in codes  # Polysomnography


def test_osa_second_followup_emits_cpap_only(osa_fu_spec):
    """Year 2 — CPAP re-emits (every_visit) but polysomnography does NOT
    (baseline_only — Review Focus #3 + #4 pin)."""
    assert osa_fu_spec, "G47.30 block missing"
    patient = _make_osa_patient()
    _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 6, 1, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="G47.30",
        followup_spec=osa_fu_spec,
        country="US",
    )
    rec2 = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 12, 1, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(1),
        chronic_code="G47.30",
        followup_spec=osa_fu_spec,
        country="US",
    )
    codes2 = {p.procedure_code for p in rec2.procedures}
    assert "99503" in codes2  # CPAP every visit
    assert "95810" not in codes2  # polysomnography already baselined


def test_osa_followup_procedure_codes_are_cpt_only_today(osa_fu_spec):
    """Phase 4d scope pin — the FHIR emit path currently codes OSA
    procedures with CPT only (via ProcedureRecord.procedure_code_us).
    SNOMED resolution + JP display on the CIF ProcedureRecord emit path
    is deferred to Phase 4d.1. This test pins the current (CPT-only)
    behavior so a future SNOMED-attachment landing is a deliberate
    change, not a stealth drift."""
    assert osa_fu_spec, "G47.30 block missing"
    patient = _make_osa_patient()
    rec = _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 6, 1, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="G47.30",
        followup_spec=osa_fu_spec,
        country="US",
    )
    # Each ProcedureRecord carries CPT code only in procedure_code / procedure_code_us.
    # No SNOMED field exists on ProcedureRecord today; the yaml's snomed: value is
    # plumbed through the simulator but dormant at FHIR emit (future Phase 4d.1).
    for proc in rec.procedures:
        if proc.procedure_code in {"99503", "95810"}:
            assert proc.procedure_code_us == proc.procedure_code
            # No snomed_code / snomed_cd attribute on ProcedureRecord.
            assert not hasattr(proc, "snomed_code")
