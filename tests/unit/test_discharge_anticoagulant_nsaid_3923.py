"""Issue #3923: a discharge prescription does not combine an anticoagulant with an NSAID.

The ``anticoagulant-plus-nsaid`` rule is contraindicated, yet the discharge reconciliation
listed only same-class duplicates, so the JP femoral-neck fracture list carried celecoxib
with enoxaparin. The rule is now reconciled: the anticoagulant is kept whichever came
first, the NSAID is dropped and logged as held.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pytest

from clinosim.modules import drug_safety
from clinosim.modules.disease.protocol import load_all_disease_protocols, load_disease_protocol
from clinosim.simulator.discharge_rx import build_discharge_rx

pytestmark = pytest.mark.unit


def _protocol(*drugs: str) -> SimpleNamespace:
    entries = [{"drug": d, "dose": "1 unit", "route": "PO", "frequency": "daily", "duration_days": 14} for d in drugs]
    return SimpleNamespace(disease_id="t3923", drugs={"discharge_oral": {"us": entries, "japan": entries}})


def _rx(patient, protocol, **kw):
    return build_discharge_rx(
        patient=patient,
        disease_id="t3923",
        protocol=protocol,
        prescriber_id="md",
        admission_time=datetime(2026, 3, 1, 9, 0),
        country_key="us",
        encounter_id="enc-3923",
        **kw,
    )


def _names(rx) -> list[str]:
    return [it["drug_name"] for it in rx.items]


@pytest.mark.parametrize("order", [("Celecoxib", "Enoxaparin"), ("Enoxaparin", "Celecoxib")])
def test_the_nsaid_is_dropped_and_the_anticoagulant_kept_in_either_order(patient_factory, order) -> None:
    patient = patient_factory(current_meds=["Celecoxib"])
    rx = _rx(patient, _protocol(*order, "Acetaminophen"), ordered_drugs=["Celecoxib"])
    names = _names(rx)
    assert "Enoxaparin" in names and "Acetaminophen" in names
    assert "Celecoxib" not in names
    held = [e for e in patient.safety_skip_log if e.event_type == "hold"]
    assert [e.candidate_drug for e in held] == ["Celecoxib"]


def test_a_home_nsaid_is_not_continued_beside_a_discharge_anticoagulant(patient_factory) -> None:
    patient = patient_factory(current_meds=["Loxoprofen"])
    names = _names(_rx(patient, _protocol("Apixaban")))
    assert "Apixaban" in names and "Loxoprofen" not in names


def test_a_home_anticoagulant_is_kept_over_a_protocol_nsaid(patient_factory) -> None:
    patient = patient_factory(current_meds=["Apixaban"])
    names = _names(_rx(patient, _protocol("Ibuprofen", "Acetaminophen")))
    assert "Apixaban" in names and "Acetaminophen" in names
    assert "Ibuprofen" not in names


def test_aspirin_with_an_anticoagulant_is_not_this_rules_business(patient_factory) -> None:
    """Aspirin is an NSAID by class only; with an anticoagulant it is an antiplatelet question."""
    patient = patient_factory(current_meds=["Apixaban"])
    assert "Aspirin" in _names(_rx(patient, _protocol("Aspirin")))


def test_the_reconciled_rule_names_the_class_it_keeps() -> None:
    assert drug_safety.discharge_reconciliation_keeps() == {"anticoagulant-plus-nsaid": "anticoagulant"}
    v = drug_safety.check_pair("Enoxaparin", "Celecoxib")
    assert drug_safety.reconciliation_keeps_candidate(v, "Enoxaparin")
    assert not drug_safety.reconciliation_drops_candidate(v, "Enoxaparin")
    assert drug_safety.reconciliation_drops_candidate(v, "Celecoxib")


def test_jp_hip_fracture_discharge_has_no_nsaid_beside_enoxaparin(patient_factory) -> None:
    patient = patient_factory(age=80)
    rx = build_discharge_rx(
        patient=patient,
        disease_id="hip_fracture",
        protocol=load_disease_protocol("hip_fracture"),
        prescriber_id="md",
        admission_time=datetime(2026, 3, 1, 9, 0),
        country_key="japan",
        encounter_id="enc-3923-hip",
    )
    names = _names(rx)
    assert "Enoxaparin" in names and "Acetaminophen" in names
    assert not [n for n in names if "nsaid" in drug_safety.resolve_classes(n)]


def test_no_protocol_declares_an_anticoagulant_and_an_nsaid_in_its_discharge_list() -> None:
    from clinosim.codes.drugs import resolve_drug

    offenders = []
    for disease_id, protocol in load_all_disease_protocols().items():
        block = protocol.drugs.get("discharge_oral")
        if not isinstance(block, dict):
            continue
        for country in ("japan", "us"):
            names = [
                resolve_drug(e["drug_id"]).names["en"] if e.get("drug_id") else str(e.get("drug") or "")
                for e in block.get(country) or []
            ]
            classes = [set(drug_safety.resolve_classes(n)) for n in names]
            for n, c in zip(names, classes, strict=True):
                if "nsaid" in c and any(
                    drug_safety.reconciliation_keeps_candidate(drug_safety.check_pair(o, n), o) for o in names if o != n
                ):
                    offenders.append(f"{disease_id}/{country}/{n}")
    assert offenders == []
