"""Outpatient follow-up keeps qualitative labs (Issue #2527): a urinalysis in a
follow-up schedule is resulted with a categorical value, as in the ED."""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_chronic_followup
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit


def test_followup_urinalysis_is_resulted() -> None:
    code = next(
        c
        for c, spec in load_chronic_followup().items()
        if isinstance(spec, dict) and "Urinalysis" in (spec.get("labs") or [])
    )
    patient = PatientProfile(patient_id="pt-ua")
    patient.age, patient.sex, patient.chronic_conditions, patient.current_medications = 65, "M", [], []
    rec = _simulate_outpatient_visit(
        patient,
        "chronic_followup",
        datetime(2026, 5, 1, 10, 0),
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code=code,
        followup_spec=load_chronic_followup()[code],
        country="US",
    )
    results = {r.lab_name: r.value for r in rec.lab_results}
    assert isinstance(results.get("Urinalysis"), str)
    assert "Creatinine" in results
