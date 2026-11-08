"""ED take-home scripts prescribe exactly one agent per required class (Issue #2865)."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.simulator.emergency import _ed_discharge_prescription
from clinosim.types.encounter import Encounter, EncounterType
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_ANTIBIOTICS = ("Trimethoprim/Sulfamethoxazole", "Nitrofurantoin", "Ciprofloxacin")


def _rx(i: int, country: str, chronic: tuple[str, ...] = ()) -> list[str]:
    patient = PatientProfile(patient_id=f"PT-{i}", age=40, sex="F")
    patient.chronic_conditions = [ChronicCondition(code=c) for c in chronic]
    t0 = datetime(2025, 3, 1, 10, 0)
    enc = Encounter(encounter_id=f"ENC-{i}", patient_id=patient.patient_id)
    enc.encounter_type = EncounterType.EMERGENCY
    enc.admission_datetime = t0
    enc.discharge_datetime = t0 + timedelta(hours=3)
    enc.discharge_disposition = DischargeDisposition.HOME
    protocol = load_encounter_condition("uti_uncomplicated")
    rx = _ed_discharge_prescription(protocol, patient, enc, ["N39.0"], country, "uti_uncomplicated")
    return [str(item["drug_name"]) for item in (rx.items if rx else [])]


@pytest.mark.parametrize("country", ["US", "JP"])
def test_uti_discharge_has_exactly_one_antibiotic(country: str) -> None:
    for i in range(60):
        abx = [d for d in _rx(i, country) if d.startswith(_ANTIBIOTICS)]
        assert len(abx) == 1, (i, abx)
        if country == "JP":
            assert not abx[0].startswith("Nitrofurantoin")


def test_g6pd_patient_falls_through_to_a_non_oxidant_antibiotic() -> None:
    for i in range(30):
        abx = [d for d in _rx(i, "US", ("D55.0",)) if d.startswith(_ANTIBIOTICS)]
        assert abx == ["Ciprofloxacin"], (i, abx)
