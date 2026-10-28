"""ED psychiatric visits: severity-conditioned screening scores and mental status exam (Issue #2129)."""

from __future__ import annotations

from datetime import datetime
from statistics import median

import pytest

from clinosim import determinism
from clinosim.locale.loader import load_demographics
from clinosim.modules.encounter.protocol import EdPhysicalExam, load_encounter_condition
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.population.engine import PersonRecord
from clinosim.modules.staff.engine import generate_roster
from clinosim.simulator.emergency import _simulate_ed_visit, ed_lab_true_value

pytestmark = pytest.mark.unit

_COND = "suicidal_ideation_depression"


def test_value_by_severity_overrides_physiology() -> None:
    spec = {"test": "C-SSRS", "value_by_severity": {"mild": 2, "moderate": 4, "severe": 5}}
    assert ed_lab_true_value(spec, "severe", 1.0) == 5.0
    assert ed_lab_true_value(spec, "mild", 1.0) == 2.0
    assert ed_lab_true_value({"test": "Na"}, "severe", 140.0) == 140.0


def _cssrs(severity: str) -> list[float]:
    cond = load_encounter_condition(_COND)
    out: list[float] = []
    for seed in range(12):
        rng = determinism.default_rng(seed)
        roster = generate_roster("medium", "US", rng)
        person = PersonRecord(
            person_id=f"T-{seed}", household_id="H", age=40, sex="F", date_of_birth=datetime(1984, 1, 1).date()
        )
        patient = activate_patient(person, rng, load_demographics("US"))
        record = _simulate_ed_visit(
            patient, {"name": _COND, **cond}, datetime(2024, 6, 1, 14), roster, rng, force_severity=severity
        )
        out += [float(r.value) for r in record.lab_results if r.lab_name == "C-SSRS"]
    return out


def test_transferred_patients_screen_with_intent_or_plan() -> None:
    mild, severe = _cssrs("mild"), _cssrs("severe")
    assert mild and severe
    assert median(mild) <= 2 and median(severe) >= 4


def test_mental_status_exam_is_a_rendered_exam_entry() -> None:
    assert "psychiatric" in EdPhysicalExam.model_fields
    tmpl = load_encounter_condition(_COND)["narrative"]["ed_note_template"]
    assert tmpl["physical_exam_en"]["psychiatric"] and tmpl["physical_exam_ja"]["psychiatric"]
