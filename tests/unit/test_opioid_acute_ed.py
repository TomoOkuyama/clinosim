"""Opioid overdose and withdrawal ED visits for opioid use disorder (Issue #2154)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime

import pytest

from clinosim.codes import lookup
from clinosim.modules.encounter.protocol import load_encounter_condition
from clinosim.modules.output.fhir_r4.medications.medications import _resolve_medication_concept
from clinosim.modules.physiology.engine import canonical_state_vars, derive_vital_signs
from clinosim.simulator.emergency import ed_treatment_response
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import BaselineVitals

pytestmark = pytest.mark.unit

_TS = datetime(2026, 5, 1, 14, 0)
_BASE = BaselineVitals(
    temperature=36.6, heart_rate=72, systolic_bp=122, diastolic_bp=76, respiratory_rate=16, spo2=98.0
)


def test_respiratory_depression_lowers_respiratory_rate() -> None:
    assert "respiratory_depression" in canonical_state_vars()
    assert PhysiologicalState().respiratory_depression == 0.0
    state = PhysiologicalState(oxygenation_impairment=0.3)
    depressed = replace(state, respiratory_depression=0.6)
    assert derive_vital_signs(depressed, _BASE, _TS)["respiratory_rate"] <= 10
    assert derive_vital_signs(state, _BASE, _TS)["respiratory_rate"] > 16


def test_naloxone_round_reverses_respiratory_depression() -> None:
    after = ed_treatment_response(PhysiologicalState(respiratory_depression=0.6))
    assert after.respiratory_depression < 0.6


def test_overdose_protocol() -> None:
    spec = load_encounter_condition("opioid_overdose")
    assert spec["requires_chronic_prefix"] == ["F11"]
    assert spec["icd10_code"] == "T40.411A"
    assert "fentanyl" in lookup("icd-10-cm", "T40.411A", "en")
    assert (spec["triage_level_min"], spec["triage_level_max"]) == (1, 2)
    assert set(spec["severity_distribution"]) == {"mild", "moderate"}  # severe overdoses are admitted
    assert all(v["respiratory_depression"] > 0 for v in spec["initial_state_impact"].values())
    names = [t["name"] for t in spec["treatment"]]
    assert any(n.startswith("Naloxone") for n in names)
    kits = [rx["drug"] for rx in spec["discharge_prescriptions"]]
    assert any("Naloxone" in k and "nasal" in k for k in kits)


def test_withdrawal_protocol() -> None:
    spec = load_encounter_condition("opioid_withdrawal")
    assert spec["requires_chronic_prefix"] == ["F11"]
    assert spec["icd10_code"] == "F11.23"
    assert lookup("icd-10-cm", "F11.23", "en") == "Opioid dependence with withdrawal"
    names = {t["name"].split()[0] for t in spec["treatment"]}
    assert {"Buprenorphine/Naloxone", "Clonidine", "Ondansetron"} <= names


@pytest.mark.parametrize(
    ("drug", "code"),
    [
        ("Naloxone 0.4mg", "7242"),
        ("Naloxone 4mg nasal spray", "7242"),
        ("Buprenorphine/Naloxone 8mg/2mg", "352364"),
        ("Clonidine 0.1mg", "2599"),
    ],
)
def test_us_drug_codes(drug: str, code: str) -> None:
    concept, _ = _resolve_medication_concept(drug, order_code="", country="US")
    assert concept["coding"][0]["code"] == code


def test_referral_is_not_a_medication_order() -> None:
    # "Referral for medication for opioid use disorder" defaulted to a
    # medication order and was emitted as an uncoded MedicationRequest.
    from clinosim.modules.order.treatment_classifier import classify_encounter_treatment
    from clinosim.types.encounter import OrderType

    assert classify_encounter_treatment("Referral for medication for opioid use disorder") == OrderType.THERAPY


def test_jp_has_no_opioid_use_disorder() -> None:
    # Both visits are gated on F11, which JP does not sample (Issue #2146).
    from clinosim.locale.loader import load_demographics

    assert not any(str(k).startswith("F11") for k in load_demographics("JP")["chronic_prevalence"])
