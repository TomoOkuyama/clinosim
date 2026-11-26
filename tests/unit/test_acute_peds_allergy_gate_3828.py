"""The take-home course of an acute pediatric visit follows the drug-allergy gate (Issue #3828).

A child with a recorded penicillin allergy was prescribed amoxicillin for otitis
media because ``_acute_visit_prescription`` never called the shared gate.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.modules.pediatric.calendar import _load_schedule
from clinosim.modules.staff.engine import StaffRoster
from clinosim.simulator.outpatient import _simulate_outpatient_visit
from clinosim.types.allergy import Allergy
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit

PENICILLIN = "764146007"


def _child(*allergy_codes: str) -> PatientProfile:
    p = PatientProfile(patient_id="pt-child")
    p.age = 2
    p.sex = "F"
    p.date_of_birth = date(2023, 5, 1)
    p.baseline_vitals = BaselineVitals(temperature=36.6, heart_rate=110, respiratory_rate=26, spo2=98.5)
    p.allergies = [
        Allergy(allergy_id=str(i), allergen_code=c, category="medication") for i, c in enumerate(allergy_codes)
    ]
    return p


def _items(patient: PatientProfile) -> list[dict]:
    rec = _simulate_outpatient_visit(
        patient,
        "pediatric_visit",
        datetime(2025, 11, 3, 10, 5),
        StaffRoster(),
        np.random.default_rng(0),
        chronic_code="pediatric_otitis_media",
        followup_spec={"labs": []},
        country="US",
        department_id="pediatrics",
    )
    assert rec.discharge_prescription is not None
    return rec.discharge_prescription.items


def test_child_without_allergy_keeps_first_line_amoxicillin() -> None:
    items = _items(_child())
    assert [i["drug_id"] for i in items] == ["amoxicillin"]
    assert items[0]["dose"] == "45mg/kg"


def test_penicillin_allergic_child_gets_the_declared_alternative() -> None:
    items = _items(_child(PENICILLIN))
    assert [i["drug_id"] for i in items] == ["cefdinir"]
    assert items[0]["dose"] == "7mg/kg"
    assert items[0]["frequency"] == "BID"
    assert items[0]["duration_days"] == 7  # age 2: the "2+" band
    assert items[0]["drug_name_ja"]


def test_alternative_the_child_is_allergic_to_too_leaves_no_antibiotic(monkeypatch: pytest.MonkeyPatch) -> None:
    from clinosim.modules import drug_safety

    real = drug_safety.allergy_skip_verdict
    # Every drug of the course is ruled out: the first line and its alternative.
    monkeypatch.setattr(
        drug_safety,
        "allergy_skip_verdict",
        lambda name, allergies: real("Amoxicillin", allergies) if name.lower() in {"amoxicillin", "cefdinir"} else None,
    )
    assert _items(_child(PENICILLIN)) == []


def test_every_declared_alternative_is_validated_at_load() -> None:
    for presentation in _load_schedule().presentations.values():
        for spec in presentation.prescriptions:
            if spec.alternative is not None:
                assert spec.alternative.alternative is None
