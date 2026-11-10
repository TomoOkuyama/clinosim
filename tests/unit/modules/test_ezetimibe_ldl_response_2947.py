"""Ezetimibe lowers LDL alone and on top of a statin (Issue #2947).

The add-on removes its fraction of the LDL the statin leaves (IMPROVE-IT: a
further ~23 %; monotherapy ~18.6 %, Pandor et al. 2009), detected by drug
class from the active medications, at the patient's same deterministic
position as the statin response. Encounter labs and the health checkup read
it through the one lipid panel.
"""

from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from clinosim.modules.health_checkup import engine as checkup
from clinosim.modules.physiology import statin_response as sr
from clinosim.modules.physiology.engine import (
    derive_lab_values,
    medication_flags_from_context,
    patient_lipid_panel,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_STATIN = HomeMedication(drug_name="Atorvastatin", dose="20mg", route="PO", frequency="daily")
_EZETIMIBE = HomeMedication(drug_name="Ezetimibe", dose="10mg", route="PO", frequency="daily")


def _patient(patient_id: str, *meds: HomeMedication) -> PatientProfile:
    patient = PatientProfile(patient_id=patient_id, age=64, sex="M")
    patient.chronic_conditions = [ChronicCondition(code="E78.5", system="icd-10-cm")]
    patient.current_medications = [
        HomeMedication(drug_name="Amlodipine", dose="5mg", route="PO", frequency="daily"),
        *meds,
    ]
    return patient


def _lipids(patient: PatientProfile) -> dict[str, float]:
    flags = medication_flags_from_context(patient)
    labs = derive_lab_values(PhysiologicalState(), sex="M", age=64, has_dyslipidemia=True, **flags)  # type: ignore[arg-type]
    return {k: labs[k] for k in ("TC", "LDL", "HDL", "TG")}


_IDS = [f"pt-2947-{i}" for i in range(12)]


@pytest.mark.parametrize("pid", _IDS)
def test_neither_leaves_the_untreated_ldl(pid: str) -> None:
    assert medication_flags_from_context(_patient(pid))["ldl_reduction"] == 0.0
    assert sr.ldl_reduction(pid, []) == 0.0


@pytest.mark.parametrize("pid", _IDS)
def test_statin_only_is_the_statin_reduction(pid: str) -> None:
    meds = [_STATIN]
    assert sr.ldl_reduction(pid, meds) == sr.statin_ldl_reduction(pid, meds)
    assert 0.30 <= sr.ldl_reduction(pid, meds) <= 0.49


@pytest.mark.parametrize("pid", _IDS)
def test_ezetimibe_on_a_statin_removes_a_further_20_to_26_percent(pid: str) -> None:
    on_statin = _lipids(_patient(pid, _STATIN))
    combined = _lipids(_patient(pid, _STATIN, _EZETIMIBE))
    further = 1 - combined["LDL"] / on_statin["LDL"]
    assert 0.20 <= further <= 0.26
    # TC follows LDL by the same mg/dL; HDL and TG unchanged (Friedewald holds).
    assert combined["TC"] == pytest.approx(on_statin["TC"] - (on_statin["LDL"] - combined["LDL"]))
    assert (combined["HDL"], combined["TG"]) == (on_statin["HDL"], on_statin["TG"])


@pytest.mark.parametrize("pid", _IDS)
def test_ezetimibe_alone_removes_16_to_21_percent(pid: str) -> None:
    untreated = _lipids(_patient(pid))
    alone = _lipids(_patient(pid, _EZETIMIBE))
    assert 0.16 <= 1 - alone["LDL"] / untreated["LDL"] <= 0.21
    assert alone["TC"] == pytest.approx(untreated["TC"] - (untreated["LDL"] - alone["LDL"]))


def test_the_add_on_uses_the_statin_responders_position() -> None:
    data = sr.statin_ldl_response()
    lo, hi = data.ldl_reduction["moderate"]
    add_lo, add_hi = data.add_on["cholesterol_absorption_inhibitor"].with_statin
    for pid in _IDS:
        statin = sr.statin_ldl_reduction(pid, [_STATIN])
        further = 1 - (1 - sr.ldl_reduction(pid, [_STATIN, _EZETIMIBE])) / (1 - statin)
        assert (further - add_lo) / (add_hi - add_lo) == pytest.approx((statin - lo) / (hi - lo))


def test_the_checkup_and_encounter_ldl_agree_with_ezetimibe() -> None:
    patient = _patient("pt-2947-checkup", _STATIN, _EZETIMIBE)
    assert patient_lipid_panel(patient)["LDL"] == pytest.approx(_lipids(patient)["LDL"])
    without = _patient("pt-2947-checkup", _STATIN)
    rng = np.random.default_rng(0)
    assert (
        checkup._derive_checkup_values(patient, rng, charted_bmi=22.5)["LDL"]
        < checkup._derive_checkup_values(without, np.random.default_rng(0), charted_bmi=22.5)["LDL"]
    )


def test_an_ezetimibe_dict_order_counts() -> None:
    order = {"drug_name": "Ezetimibe 10mg", "dose": "10mg"}
    assert 0.16 <= sr.ldl_reduction("pt-2947-order", [order]) <= 0.21


def test_the_model_rejects_an_unknown_or_statin_class_and_bad_ranges() -> None:
    raw = sr.statin_ldl_response().model_dump()
    good = raw["add_on"]["cholesterol_absorption_inhibitor"]
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate({**raw, "add_on": {"no_such_class": good}})
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate({**raw, "add_on": {"statin": good}})
    with pytest.raises(ValidationError):
        sr.StatinLdlResponse.model_validate(
            {**raw, "add_on": {"cholesterol_absorption_inhibitor": {**good, "with_statin": (0.30, 0.20)}}}
        )
