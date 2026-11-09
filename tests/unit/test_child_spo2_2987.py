"""Issue #2987: a healthy or mildly ill child keeps a normal SpO2.

A healthy child's baseline SpO2 centres on 99 % (adults keep 97.5 %), and an
upper-airway or ear infection (URI, otitis media) does not lower SpO2 through
its fever: only a lower-respiratory presentation (bronchiolitis) does.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pytest

from clinosim.locale.loader import load_demographics
from clinosim.modules.patient.activator import activate_patient
from clinosim.modules.pediatric.calendar import pediatric_presentation
from clinosim.modules.physiology.engine import (
    apply_disease_onset,
    derive_vital_signs,
    initialize_state,
    room_air_saturation,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.population import PersonRecord

pytestmark = pytest.mark.unit

_DEMO = load_demographics("US")
_WHEN = datetime(2026, 3, 2, 10, 5)


def _activate(age: int, seed: int):
    person = PersonRecord(
        person_id=f"P{seed}",
        household_id="H1",
        age=age,
        sex="F",
        date_of_birth=date(2026 - age, 1, 1),
        chronic_conditions=[],
    )
    return activate_patient(person, np.random.default_rng(seed), _DEMO)


def _true_spo2(patient, presentation_id: str | None = None, visit_state: str = "febrile") -> float:
    state = initialize_state(patient.physiological_profile, patient.chronic_conditions, patient.patient_id)
    state.timestamp = _WHEN
    pulmonary = True
    if presentation_id is not None:
        presentation = pediatric_presentation(presentation_id)
        assert presentation is not None
        state = apply_disease_onset(state, visit_state, presentation.state_impact)
        pulmonary = presentation.pulmonary_involvement
    vitals = derive_vital_signs(
        state, patient.baseline_vitals, _WHEN, age_months=patient.age * 12, pulmonary_inflammation=pulmonary
    )
    return vitals["spo2"]


def test_healthy_five_year_old_derived_spo2_is_at_least_96() -> None:
    values = [_true_spo2(_activate(5, seed)) for seed in range(200)]
    assert min(values) >= 96.0, min(values)


@pytest.mark.parametrize("visit", ["pediatric_uri", "pediatric_otitis_media"])
def test_febrile_uri_or_otitis_does_not_lower_spo2(visit: str) -> None:
    for seed in range(50):
        child = _activate(5, seed)
        assert _true_spo2(child, visit, "febrile") == _true_spo2(child), seed
        assert _true_spo2(child, visit, "febrile") >= 96.0, seed


def test_bronchiolitis_still_lowers_spo2_with_fever() -> None:
    presentation = pediatric_presentation("pediatric_bronchiolitis")
    assert presentation is not None and presentation.pulmonary_involvement
    child = _activate(1, 3)
    assert _true_spo2(child, "pediatric_bronchiolitis", "febrile") < _true_spo2(child)


def test_room_air_saturation_skips_inflammation_without_lung_involvement() -> None:
    state = PhysiologicalState(inflammation_level=0.75)
    assert room_air_saturation(state, 99.0, pulmonary_inflammation=False) == 99.0
    assert room_air_saturation(state, 99.0) == pytest.approx(94.5)


def test_adult_baseline_spo2_is_unchanged() -> None:
    values = [_activate(40, seed).baseline_vitals.spo2 for seed in range(300)]
    assert max(values) <= 99.0
    assert 97.2 <= float(np.mean(values)) <= 97.6
