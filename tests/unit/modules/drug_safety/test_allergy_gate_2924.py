"""Prescriptions are checked against the patient's recorded allergies (Issue #2924).

No prescribing path used to read ``patient.allergies``: an aspirin-allergic
patient was discharged on ibuprofen, a sulfonamide-allergic patient started
on hydrochlorothiazide, and amoxicillin was ordered without a penicillin
check. ``allergy_contraindications.yaml`` maps each medication allergen to
the drug classes it rules out (block) or flags (caution).
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pydantic
import pytest

from clinosim.modules import drug_safety
from clinosim.modules.drug_safety._models import AllergyContraindicationsFile
from clinosim.simulator.emergency import _ed_medication_skipped
from clinosim.simulator.medication_pipeline import allergy_blocked, apply_drug_safety_gate_to_orders
from clinosim.types.allergy import Allergy
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_WHEN = datetime(2026, 3, 1, 10, 0)
PENICILLIN, ASPIRIN, SULFONAMIDE = "764146007", "387458008", "115556009"
EGG, NKA = "735038006", "716186003"


def _allergy(code: str, **kw: object) -> Allergy:
    return Allergy(allergy_id="1", allergen_code=code, category="medication", **kw)  # type: ignore[arg-type]


def _patient(*allergies: Allergy) -> PatientProfile:
    p = PatientProfile(patient_id="PT-1", age=40, sex="F")
    p.allergies = list(allergies)
    return p


def _order(drug: str) -> Order:
    return Order(
        order_id="ORD-1",
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        order_code="",
        display_name=drug,
        urgency="routine",
        clinical_intent="test",
        ordered_datetime=_WHEN,
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )


def _verdicts(drug: str, *codes: str) -> dict[str, str]:
    return {str(v.rule_id): v.severity for v in drug_safety.check_candidate_against_allergies(drug, list(codes))}


@pytest.mark.parametrize("drug", ["Amoxicillin 500mg", "Amoxicillin/clavulanate 875/125mg", "Ampicillin"])
def test_penicillin_allergy_blocks_penicillins(drug: str) -> None:
    assert _verdicts(drug, PENICILLIN) == {"penicillin-allergy-penicillins": "contraindicated"}


def test_penicillin_allergy_only_cautions_cephalosporins_and_spares_carbapenems() -> None:
    assert _verdicts("Cefazolin", PENICILLIN) == {"penicillin-allergy-cephalosporins": "moderate"}
    assert _verdicts("Meropenem", PENICILLIN) == {}


@pytest.mark.parametrize("drug", ["Ibuprofen 400mg", "Naproxen", "Ketorolac", "Loxoprofen", "Meloxicam"])
def test_aspirin_allergy_blocks_nsaids(drug: str) -> None:
    assert _verdicts(drug, ASPIRIN) == {"aspirin-allergy-nsaids": "contraindicated"}


def test_aspirin_allergy_blocks_aspirin_as_antiplatelet_without_an_analgesic_substitute() -> None:
    assert _verdicts("Aspirin 81mg", ASPIRIN) == {"aspirin-allergy-aspirin": "contraindicated"}
    (verdict,) = drug_safety.check_candidate_against_allergies("Aspirin 81mg", [ASPIRIN])
    assert verdict.substitution_hint is None


def test_aspirin_allergy_cautions_celecoxib() -> None:
    assert _verdicts("Celecoxib", ASPIRIN) == {"aspirin-allergy-cox2-selective": "moderate"}


def test_sulfonamide_allergy_blocks_tmp_smx_but_only_cautions_non_antibiotics() -> None:
    assert _verdicts("Trimethoprim/Sulfamethoxazole 160/800mg", SULFONAMIDE) == {
        "sulfonamide-allergy-sulfonamide-antibiotics": "contraindicated"
    }
    for drug in ("Hydrochlorothiazide 12.5mg", "Furosemide 40mg"):
        assert _verdicts(drug, SULFONAMIDE) == {"sulfonamide-allergy-nonantibiotic-sulfonamides": "moderate"}


@pytest.mark.parametrize("drug", ["Amoxicillin", "Ibuprofen", "Trimethoprim/Sulfamethoxazole", "Hydrochlorothiazide"])
def test_nka_and_unrelated_allergies_block_nothing(drug: str) -> None:
    for allergies in ([Allergy(allergen_code=NKA, is_nka=True)], [_allergy(EGG)]):
        assert drug_safety.allergy_skip_verdict(drug, allergies) is None
        assert drug_safety.check_candidate_against_allergies(drug, drug_safety.allergy_entries(allergies)) == []


def test_only_active_unrefuted_allergies_count() -> None:
    allergies = [
        _allergy(PENICILLIN, clinical_status="resolved"),
        _allergy(ASPIRIN, verification_status="refuted"),
        _allergy(SULFONAMIDE, verification_status="unconfirmed"),
    ]
    assert drug_safety.allergy_entries(allergies) == [SULFONAMIDE]


def test_allergy_conflict_names_the_allergy() -> None:
    (verdict,) = drug_safety.check_candidate_against_allergies("Amoxicillin", [PENICILLIN])
    assert drug_safety.conflict_display(verdict) == ("Penicillin allergy", "ペニシリンアレルギー")


def test_order_gate_substitutes_acetaminophen_for_ibuprofen_in_aspirin_allergy() -> None:
    patient = _patient(_allergy(ASPIRIN))
    out = apply_drug_safety_gate_to_orders(
        [_order("Ibuprofen 400mg")], patient=patient, encounter_id="ENC-1", ordered_datetime=_WHEN
    )
    assert [o.display_name for o in out] == ["Acetaminophen"]
    (skip,) = patient.safety_skip_log
    assert skip.verdict.rule_id == "aspirin-allergy-nsaids"
    assert skip.substituted_with == "Acetaminophen"
    assert skip.active_conflict == "Aspirin allergy"


def test_order_gate_drops_amoxicillin_in_penicillin_allergy() -> None:
    patient = _patient(_allergy(PENICILLIN))
    out = apply_drug_safety_gate_to_orders(
        [_order("Amoxicillin 500mg")], patient=patient, encounter_id="ENC-1", ordered_datetime=_WHEN
    )
    assert out == []
    assert patient.safety_skip_log[0].verdict.rule_id == "penicillin-allergy-penicillins"


def test_order_gate_substitutes_the_disease_alternative_for_a_penicillin() -> None:
    protocol = SimpleNamespace(
        disease_id="fixture",
        drugs={
            "alternative_penicillin_allergy": {
                "_indication_tag": "antimicrobial_penicillin_class",
                "us": [{"drug_id": "levofloxacin", "dose": "750mg IV daily"}],
            }
        },
    )
    patient = _patient(_allergy(PENICILLIN))
    out = apply_drug_safety_gate_to_orders(
        [_order("Ampicillin/Sulbactam 3g IV")],
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=_WHEN,
        protocol=protocol,
    )
    assert [o.display_name for o in out] == ["Levofloxacin"]
    assert patient.safety_skip_log[0].substituted_with == "Levofloxacin"


def test_order_gate_keeps_hctz_with_a_caution_note_in_sulfonamide_allergy() -> None:
    patient = _patient(_allergy(SULFONAMIDE))
    out = apply_drug_safety_gate_to_orders(
        [_order("Hydrochlorothiazide 12.5mg")], patient=patient, encounter_id="ENC-1", ordered_datetime=_WHEN
    )
    assert [o.display_name for o in out] == ["Hydrochlorothiazide 12.5mg"]
    assert out[0].notes and "sulfonamide" in out[0].notes[0]["text"].lower()
    assert patient.safety_skip_log == []


def test_order_gate_keeps_amoxicillin_without_a_penicillin_allergy() -> None:
    out = apply_drug_safety_gate_to_orders(
        [_order("Amoxicillin 500mg")], patient=_patient(_allergy(EGG)), encounter_id="ENC-1", ordered_datetime=_WHEN
    )
    assert [o.display_name for o in out] == ["Amoxicillin 500mg"]


def test_ed_gate_skips_tmp_smx_in_sulfonamide_allergy() -> None:
    patient = _patient(_allergy(SULFONAMIDE))
    assert _ed_medication_skipped(
        "Trimethoprim/Sulfamethoxazole 160/800mg", patient, ["N39.0"], [], "ENC-1", _WHEN, "uti", "ed_discharge_rx"
    )
    assert patient.safety_skip_log[-1].verdict.rule_id == "sulfonamide-allergy-sulfonamide-antibiotics"
    assert not _ed_medication_skipped("Hydrochlorothiazide", patient, [], [], "ENC-1", _WHEN, "htn", "ed_treatment")


def test_prescription_helper_blocks_and_logs() -> None:
    patient = _patient(_allergy(ASPIRIN))
    assert allergy_blocked(patient, "Ibuprofen", encounter_id="ENC-1", timestamp=_WHEN)
    assert not allergy_blocked(patient, "Acetaminophen", encounter_id="ENC-1", timestamp=_WHEN)
    assert [s.candidate_drug for s in patient.safety_skip_log] == ["Ibuprofen"]


def test_discharge_rx_replaces_ibuprofen_in_aspirin_allergy() -> None:
    from clinosim.simulator.discharge_rx import build_discharge_rx

    patient = _patient(_allergy(ASPIRIN))
    protocol = SimpleNamespace(
        disease_id="fixture",
        drugs={"discharge_oral": {"us": [{"drug": "Ibuprofen", "dose": "400mg", "route": "PO", "frequency": "tid"}]}},
    )
    rx = build_discharge_rx(
        patient=patient,
        protocol=protocol,  # type: ignore[arg-type]
        disease_id="fixture",
        prescriber_id="DR-1",
        admission_time=_WHEN,
        encounter_id="ENC-1",
    )
    assert [it["drug_name"] for it in rx.items] == ["Acetaminophen"]
    assert patient.safety_skip_log[0].substituted_with == "Acetaminophen"


def test_home_medication_derivation_drops_an_allergy_conflict() -> None:
    from clinosim.modules.patient.activator import _log_allergy_skip

    log: list = []
    allergies = [_allergy(ASPIRIN)]
    meds = [HomeMedication(drug_name="Aspirin"), HomeMedication(drug_name="Atorvastatin")]
    kept = [m for m in meds if not _log_allergy_skip(m.drug_name, allergies, log)]
    assert [m.drug_name for m in kept] == ["Atorvastatin"]
    assert log[0].verdict.rule_id == "aspirin-allergy-aspirin"


def _rule(**overrides: object) -> dict:
    rule = {
        "id": "r",
        "allergen_code": PENICILLIN,
        "drug_classes": ["antibiotic.penicillin"],
        "severity": "contraindicated",
        "rationale": {"en": "x", "ja": "x"},
        "source": "s",
    }
    rule.update(overrides)
    return rule


def test_yaml_model_rejects_unknown_keys_food_allergens_and_unknown_classes() -> None:
    AllergyContraindicationsFile.model_validate({"rules": [_rule()]})
    for bad in (_rule(typo=1), _rule(allergen_code=EGG), _rule(drug_classes=["antibiotic.penicilin"])):
        with pytest.raises(pydantic.ValidationError):
            AllergyContraindicationsFile.model_validate({"rules": [bad]})
