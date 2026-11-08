"""Statins are stepped up on the measured, not the latent, LDL (Issue #2927).

The longitudinal ``lipid_escalate_high_intensity_e78`` event used to switch
a dyslipidemia patient to Rosuvastatin 20 mg whenever the untreated LDL
latent was above 160 mg/dL, so patients at goal on their statin were moved
to high intensity. It is retired (rate 0, kept so the engine's per-year draw
is unchanged); the step-up is the titration at the follow-up visit on the
measured lipid panel (``simulator/statin_monitoring.py``, Issue #2877).
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pytest

from clinosim.modules.longitudinal.loader import load_attribute_specs
from clinosim.modules.longitudinal.patterns.event import step
from clinosim.modules.physiology.statin_response import statin_intensity
from clinosim.simulator import statin_monitoring as sm
from clinosim.types.encounter import OrderResult
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit


def _patient(*codes: str) -> PatientProfile:
    patient = PatientProfile(patient_id="pt-2927", age=58, sex="F")
    patient.chronic_conditions = [ChronicCondition(code=c, system="icd-10-cm") for c in codes]
    patient.current_medications = [
        HomeMedication(drug_name="Atorvastatin", dose="10mg", route="PO", frequency="daily"),
    ]
    return patient


def _panel(patient: PatientProfile, ldl: float) -> None:
    sm.note_lipid_panel(patient, date(2023, 1, 10), [OrderResult(lab_name="LDL", value=ldl, unit="mg/dL")])


def test_latent_ldl_event_never_fires_and_keeps_its_single_draw() -> None:
    load_attribute_specs.cache_clear()
    spec = load_attribute_specs()["lipid_escalate_high_intensity_e78"].body
    for seed in range(50):
        rng = np.random.default_rng(seed)
        result = step(["E78"], [], rng, spec, context={"continuous": {"ldl": 280.0}})
        assert not result.fired
        assert result.med_additions == [] and result.med_removals == []
        # One draw, as before: the attributes after it see the same stream.
        reference = np.random.default_rng(seed)
        reference.random()
        assert rng.random() == reference.random()


def test_patient_at_goal_on_moderate_intensity_is_not_escalated() -> None:
    patient = _patient("E78")
    assert statin_intensity(patient.current_medications[0]) == "moderate"
    _panel(patient, 98.0)
    assert sm.titrate_statin(patient, date(2023, 4, 10), "US") is None
    statin = sm.current_statin(patient)
    assert statin is not None and statin.drug_name == "Atorvastatin" and statin.dose == "10mg"
    assert statin_intensity(statin) == "moderate"


def test_patient_above_goal_is_escalated_by_titration() -> None:
    patient = _patient("E78")
    _panel(patient, 196.0)
    step_up = sm.titrate_statin(patient, date(2023, 4, 10), "US")
    assert step_up is not None and step_up.ldl == 196.0
    statin = sm.current_statin(patient)
    assert statin is not None and statin.dose == "40mg"
    assert statin_intensity(statin) == "high"
