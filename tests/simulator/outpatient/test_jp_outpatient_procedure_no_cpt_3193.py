"""A JP outpatient follow-up procedure without a K-code carries no CPT code
as its primary ``procedure_code`` (Issue #3193).

``chronic_followup.yaml`` follow-up procedures (C22 abdominal ultrasound,
C50 mammography, ...) carry a CPT code and no 診療報酬 K-code. The primary
code is the country's own procedure code system only (code-mapping spec: no
other country's system as a fallback); the CPT code stays in
``procedure_code_us``.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile

C22_CPT = "76700"  # Abdominal ultrasound (CPT); no K-code in the catalog


def _visit(country: str):
    spec = load_chronic_followup().get("C22")
    assert spec
    assert all(not p.get("jp_code") for p in spec.get("procedures") or [])
    patient = PatientProfile(patient_id=f"POP-C22-{country}", sex="M", age=60, date_of_birth=date(1964, 1, 1))
    return _simulate_outpatient_visit(
        patient=patient,
        visit_type="chronic_followup",
        visit_date=datetime(2024, 3, 15, 10, 0),
        roster=StaffRoster(),
        rng=np.random.default_rng(0),
        chronic_code="C22",
        followup_spec=spec,
        country=country,
    )


def _ultrasound(rec):
    procs = [p for p in rec.procedures if p.procedure_code_us == C22_CPT]
    assert len(procs) == 1
    return procs[0]


def test_jp_outpatient_procedure_without_k_code_has_no_cpt_primary_code():
    proc = _ultrasound(_visit("JP"))
    assert proc.procedure_code == ""
    assert proc.procedure_code_jp == ""
    assert proc.procedure_code_us == C22_CPT


def test_us_outpatient_procedure_keeps_cpt_primary_code():
    assert _ultrasound(_visit("US")).procedure_code == C22_CPT
