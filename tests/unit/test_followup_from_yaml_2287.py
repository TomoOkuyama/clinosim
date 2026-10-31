"""Issue #2287: follow-up vitals and intervals come from chronic_followup.yaml
in the simulator, the population calendar and the outpatient note."""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import numpy as np
import pytest

from clinosim.locale.loader import (
    chronic_followup_interval_months,
    chronic_followup_vitals,
    load_chronic_followup,
)
from clinosim.modules.document.narrative.template_generator import TemplateNarrativeGenerator
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.document import DocumentType, NarrativeContext
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_RECORD_FIELDS = {
    "bp": ("systolic_bp", "diastolic_bp"),
    "hr": ("heart_rate",),
    "spo2": ("spo2",),
    "rr": ("respiratory_rate",),
    "temp": ("temperature_celsius",),
}

_FOLLOWED = sorted(
    code for code, spec in load_chronic_followup().items() if not code.startswith("_") and isinstance(spec, dict)
)


def _patient(code: str) -> PatientProfile:
    p = PatientProfile(patient_id=f"pt-{code}")
    p.age = 60
    p.sex = "F"
    p.chronic_conditions = []
    p.current_medications = []
    return p


@pytest.mark.parametrize("code", [c for c in _FOLLOWED if chronic_followup_vitals(c) is not None])
def test_vitals_taken_equal_the_yaml_list(code: str) -> None:
    rec = _simulate_outpatient_visit(
        _patient(code),
        "chronic_followup",
        datetime(2026, 5, 1, 10, 0),
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code=code,
        followup_spec=load_chronic_followup()[code],
        country="US",
    )
    vs = rec.vital_signs[0]
    expected = chronic_followup_vitals(code) or frozenset()
    for group, attrs in _RECORD_FIELDS.items():
        for attr in attrs:
            assert (getattr(vs, attr) is not None) is (group in expected), (code, attr)


def test_every_vitals_token_is_known() -> None:
    for code in _FOLLOWED:
        chronic_followup_vitals(code)  # raises on an unknown token


def test_interval_is_the_shortest_scheduled_one() -> None:
    data = load_chronic_followup()
    assert chronic_followup_interval_months(["I10"]) == data["I10"]["follow_up_interval_months"]
    assert chronic_followup_interval_months(["I10", "N18"]) == 1
    assert chronic_followup_interval_months(["not-followed"]) is None


@pytest.mark.parametrize("code", ["I10", "N18", "E11.9", "M81"])
def test_note_interval_matches_the_schedule(code: str) -> None:
    p = PatientProfile(patient_id="pt-note")
    p.chronic_conditions = [SimpleNamespace(code=code)]
    p.current_medications = []
    ctx = NarrativeContext(
        patient=p,
        encounter=SimpleNamespace(encounter_id="enc-1", admission_datetime=datetime(2026, 5, 1, 10, 0)),
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
        target_lang="en",
        locale="us",
    )
    months = load_chronic_followup()[code]["follow_up_interval_months"]
    line = TemplateNarrativeGenerator()._compose_follow_up_line(ctx)
    assert f"in {months} month" in line
