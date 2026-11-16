"""Issue #3274 (part a): the AF admission order set gives one rate-control agent.

The ``atrial_fibrillation_rvr`` first-line list names alternatives (a
non-dihydropyridine calcium-channel blocker and a beta-blocker), but every
entry used to be ordered: diltiazem was started, the beta-blocker was then
blocked against it and digoxin "substituted" for it. Diltiazem was given in
heart failure (the YAML's ``contraindication`` string had no reader), and the
protocol's IV beta-blocker was added on top of a home beta-blocker.

Now ``drugs.first_line.select: one_of`` makes the list a choice: the drug-safety
gate gives the first entry that passes and drops the rest, a non-DHP CCB is
avoided in heart failure (``disease_contraindications.yaml``), two
beta-blockers are a duplication (``contraindications.yaml``), and only when
every entry is ruled out does the gate add the substitute of the first entry
that has one (digoxin beside the home beta-blocker).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from clinosim.determinism import default_rng
from clinosim.modules import drug_safety
from clinosim.modules.disease.protocol import load_disease_protocol, validate_first_line_select
from clinosim.modules.order.engine import first_line_alternative_groups, place_admission_orders
from clinosim.simulator.medication_pipeline import (
    apply_drug_safety_gate_to_admission_orders,
    apply_drug_safety_gate_to_orders,
)
from clinosim.types.encounter import Order, OrderType
from clinosim.types.patient import ChronicCondition, HomeMedication, PatientProfile

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 3, 1, 10, 0)
_ENC = "ENC-AF-1"
_RATE_CONTROL = {"Diltiazem", "Metoprolol", "Landiolol hydrochloride", "Digoxin"}


def _patient(*home: str, hf: bool = False) -> PatientProfile:
    p = PatientProfile(patient_id="PT-AF", age=72, sex="M")
    p.current_medications = [HomeMedication(drug_name=d, drug_name_ja=d, dose="", frequency="") for d in home]
    p.chronic_conditions = [ChronicCondition(code="I50")] if hf else []  # type: ignore[call-arg]
    return p


def _admission(patient: PatientProfile, country_key: str) -> list[Order]:
    protocol = load_disease_protocol("atrial_fibrillation_rvr")
    dumped = protocol.model_dump()
    orders = place_admission_orders(dumped, patient.patient_id, _ENC, _ADM, country_key, default_rng(7))
    return apply_drug_safety_gate_to_admission_orders(
        orders,
        patient,
        _ENC,
        _ADM,
        "DR-1",
        protocol=protocol,
        country="US" if country_key == "us" else "JP",
        alternative_groups=first_line_alternative_groups(dumped, _ENC, country_key),
    )


def _rate_control(orders: list[Order]) -> list[str]:
    return sorted(
        {o.display_name for o in orders if o.order_type == OrderType.MEDICATION and o.display_name in _RATE_CONTROL}
    )


# --- YAML ---------------------------------------------------------------------


def test_af_first_line_is_a_choice_without_dead_contraindication_strings() -> None:
    first_line = load_disease_protocol("atrial_fibrillation_rvr").drugs["first_line"]
    assert first_line["select"] == "one_of"
    for country in ("us", "japan"):
        assert all("contraindication" not in entry for entry in first_line[country])
    # JCS/JHRS 2020: the beta-blocker is the first choice in Japan.
    assert first_line["japan"][0]["drug_id"] == "landiolol"


def test_an_unknown_first_line_select_is_rejected() -> None:
    with pytest.raises(ValueError, match="select"):
        validate_first_line_select("x", {"first_line": {"select": "any", "us": []}})
    validate_first_line_select("x", {"first_line": {"select": "one_of", "us": []}})
    validate_first_line_select("x", {"first_line": {"us": []}})


def test_groups_name_the_first_line_orders_only_for_a_choice() -> None:
    dumped = load_disease_protocol("atrial_fibrillation_rvr").model_dump()
    assert first_line_alternative_groups(dumped, _ENC, "us") == ((f"ORD-{_ENC}-ADM-M01", f"ORD-{_ENC}-ADM-M02"),)
    assert first_line_alternative_groups({"drugs": {"first_line": {"us": [{"drug_id": "aspirin"}]}}}, _ENC, "us") == ()


# --- drug-safety rules ----------------------------------------------------------


def test_two_beta_blockers_are_a_duplication() -> None:
    v = drug_safety.check_pair("Metoprolol", "Metoprolol succinate")
    assert v.rule_id == "beta-blocker-plus-beta-blocker" and v.default_action == "skip"
    assert drug_safety.check_pair("Landiolol hydrochloride", "Bisoprolol").rule_id == "beta-blocker-plus-beta-blocker"


@pytest.mark.parametrize("drug", ["Diltiazem", "Verapamil"])
def test_a_non_dhp_ccb_is_avoided_in_heart_failure(drug: str) -> None:
    verdicts = drug_safety.check_candidate_against_disease_state(drug, [("I50", "")])
    assert [v.rule_id for v in verdicts] == ["non-dhp-ccb-in-heart-failure"]
    assert verdicts[0].default_action == "skip"
    assert drug_safety.check_candidate_against_disease_state("Amlodipine", [("I50", "")]) == []


# --- admission order set ----------------------------------------------------------


def test_us_without_heart_failure_gets_diltiazem_alone() -> None:
    patient = _patient()
    assert _rate_control(_admission(patient, "us")) == ["Diltiazem"]
    assert patient.safety_skip_log == []


def test_us_heart_failure_gets_metoprolol_instead_of_diltiazem() -> None:
    patient = _patient(hf=True)
    assert _rate_control(_admission(patient, "us")) == ["Metoprolol"]
    [skip] = patient.safety_skip_log
    assert skip.candidate_drug == "Diltiazem"
    assert skip.verdict.rule_id == "non-dhp-ccb-in-heart-failure"
    assert skip.substituted_with == "Metoprolol" and skip.substituted_with_ja == "メトプロロール"


def test_us_home_beta_blocker_gets_no_second_beta_blocker_but_digoxin() -> None:
    patient = _patient("Metoprolol succinate")
    orders = _admission(patient, "us")
    assert _rate_control(orders) == ["Digoxin"]
    skips = {s.candidate_drug: s for s in patient.safety_skip_log}
    assert skips["Diltiazem"].verdict.rule_id == "bb-plus-non-dhp-ccb"
    assert skips["Diltiazem"].substituted_with == "Digoxin"
    assert skips["Metoprolol"].verdict.rule_id == "beta-blocker-plus-beta-blocker"
    assert skips["Metoprolol"].substituted_with is None


@pytest.mark.parametrize("hf", [False, True])
def test_jp_gets_landiolol_alone(hf: bool) -> None:
    patient = _patient(hf=hf)
    assert _rate_control(_admission(patient, "japan")) == ["Landiolol hydrochloride"]
    assert patient.safety_skip_log == []


def test_jp_home_beta_blocker_gets_digoxin() -> None:
    patient = _patient("Bisoprolol", hf=True)
    assert _rate_control(_admission(patient, "japan")) == ["Digoxin"]


def test_an_unchosen_alternative_and_its_maintenance_order_are_dropped() -> None:
    def order(oid: str, drug: str, prior: str = "") -> Order:
        return Order(
            order_id=oid,
            encounter_id=_ENC,
            patient_id="PT-AF",
            order_type=OrderType.MEDICATION,
            display_name=drug,
            ordered_datetime=_ADM,
            prior_order_id=prior,
        )

    candidates = [order("A", "Diltiazem"), order("B", "Metoprolol"), order("B-MAINT", "Metoprolol", prior="B")]
    out = apply_drug_safety_gate_to_orders(
        candidates,
        patient=_patient(),
        encounter_id=_ENC,
        ordered_datetime=_ADM,
        country="US",
        alternative_groups=[("A", "B")],
    )
    assert [o.order_id for o in out] == ["A"]
