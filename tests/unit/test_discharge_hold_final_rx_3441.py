"""A discharge hold is logged only for a drug left off the discharge Rx (Issue #3441).

The disease protocol's admission-time ``medication_holds`` are re-applied at
discharge only when the entry says ``applies_at_discharge``; a hold is logged
once the final item list lacks the drug, stamped with the discharge time.
"""

from __future__ import annotations

from datetime import datetime

import numpy as np
import pytest

from clinosim.codes.drugs import drug_key
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.discharge_rx import build_discharge_rx

pytestmark = pytest.mark.unit

ADMISSION = datetime(2026, 1, 1, 10, 30)
DISCHARGE = datetime(2026, 1, 8, 13, 30)


def _rx(patient, disease_id: str, seed: int = 0, renal: float = 1.0, **kw):
    return build_discharge_rx(
        patient,
        disease_id,
        load_disease_protocol(disease_id),
        "PR-1",
        ADMISSION,
        np.random.default_rng(seed),
        country_key=kw.pop("country_key", "us"),
        final_renal_function=renal,
        discharge_time=DISCHARGE,
        **kw,
    )


def _hold_keys(patient) -> list[str]:
    return [drug_key(e.candidate_drug) for e in patient.safety_skip_log if e.event_type == "hold"]


@pytest.mark.parametrize("country", ["us", "jp"])
def test_acute_hf_furosemide_prescribed_is_not_held(patient_factory, country) -> None:
    for seed in range(20):
        patient = patient_factory(current_meds=["Furosemide"])
        rx = _rx(
            patient, "heart_failure_exacerbation", seed, country_key=country, ordered_drugs=("Furosemide 40mg IV",)
        )
        prescribed = {drug_key(i["drug_name"]) for i in rx.items}
        assert "furosemide" in prescribed
        assert "furosemide" not in _hold_keys(patient)


def test_hf_hold_is_admission_only() -> None:
    holds = load_disease_protocol("heart_failure_exacerbation").medication_holds
    assert holds and not any(h.get("applies_at_discharge") for h in holds)


def test_antithrombotic_holds_of_intracranial_hemorrhage_apply_at_discharge() -> None:
    holds = load_disease_protocol("hemorrhagic_stroke").medication_holds
    assert holds and all(h.get("applies_at_discharge") is True for h in holds)


def test_a_discharge_hold_is_stamped_at_discharge(patient_factory) -> None:
    patient = patient_factory(current_meds=["Lisinopril"])
    _rx(patient, "heart_failure_exacerbation", renal=0.2)
    entries = [e for e in patient.safety_skip_log if e.event_type == "hold"]
    assert entries, "the renal-impairment hold of Lisinopril is logged"
    assert {e.timestamp for e in entries} == {DISCHARGE.isoformat()}


def test_discharge_time_defaults_to_admission(patient_factory) -> None:
    patient = patient_factory(current_meds=["Lisinopril"])
    build_discharge_rx(
        patient,
        "heart_failure_exacerbation",
        load_disease_protocol("heart_failure_exacerbation"),
        "PR-1",
        ADMISSION,
        np.random.default_rng(0),
        country_key="us",
        final_renal_function=0.2,
    )
    assert {e.timestamp for e in patient.safety_skip_log if e.event_type == "hold"} == {ADMISSION.isoformat()}
