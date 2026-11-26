"""An infectious complication gets an antibiotic from its onset (Issue #3543):
the actions a disease YAML declares are spelled one way, and the antibiotic
action is executed from the first-line antibiotics of a named protocol."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.codes.drugs import drug_classes
from clinosim.datafiles import load_data_yaml
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator import daily_loop as dl
from clinosim.simulator.complication_actions import (
    antibiotic_actions_of,
    canonical_action,
    complication_action_rules,
    first_line_antibiotics,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_DISEASES = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
ADMIT = datetime(2026, 6, 18, 9, 0)
DAY = 4


def _complications() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(_DISEASES.glob("*.yaml")):
        for comp in load_data_yaml(path).get("complications") or []:
            out.append((path.stem, comp))
    return out


def _antibiotic_like(action: str) -> bool:
    return "antibiotic" in action.lower()


def test_aliases_resolve_to_one_canonical_key() -> None:
    assert canonical_action("start_antibiotics") == "start_antibiotic"
    assert canonical_action("antibiotics") == "start_antibiotic"
    assert canonical_action("broad_spectrum_antibiotics") == "start_broad_spectrum_antibiotic"
    assert canonical_action("icu_transfer") == "icu_transfer"


def test_disease_yamls_use_only_known_antibiotic_action_keys() -> None:
    rules = complication_action_rules()
    known = set(rules.antibiotic_actions) | set(rules.not_executed_antibiotic_actions)
    for disease, comp in _complications():
        for action in comp.get("actions") or []:
            if isinstance(action, str) and _antibiotic_like(action):
                assert action in known, f"{disease}/{comp['name']}: unknown antibiotic action {action!r}"
                assert action not in rules.aliases, f"{disease}/{comp['name']}: write {rules.aliases[action]!r}"


def test_every_executed_antibiotic_complication_has_a_regimen_or_is_listed() -> None:
    rules = complication_action_rules()
    for disease, comp in _complications():
        for action in antibiotic_actions_of(comp):
            mapped = comp["name"] in rules.antibiotic_actions[action]
            assert mapped or comp["name"] in rules.no_regimen, f"{disease}/{comp['name']} has no regimen for {action}"
    for action, by_complication in rules.antibiotic_actions.items():
        for name, protocol_id in by_complication.items():
            for country in ("us", "japan"):
                regimen = first_line_antibiotics(load_disease_protocol(protocol_id).drugs.get("first_line"), country)
                assert regimen, f"{action}/{name}: {protocol_id} has no {country} first-line antibiotic"
                assert all("antibiotic" in drug_classes(e["drug_id"]) for e in regimen)


def test_first_line_antibiotics_is_one_deterministic_antibiotic() -> None:
    block = {
        "us": [
            {"drug_id": "acetaminophen", "dose": "1000mg IV q6h"},
            {"drug_id": "vancomycin", "dose": "1g IV q12h", "probability": 0.5},
            {"drug_id": "ceftriaxone", "dose": "1g IV daily"},
            {"drug_id": "ciprofloxacin", "dose": "400mg IV q12h"},
        ]
    }
    assert [e["drug_id"] for e in first_line_antibiotics(block, "us")] == ["ceftriaxone"]
    assert first_line_antibiotics(block, "japan") == []


def _stay(country: str = "us", allergies=None):
    patient = PatientProfile(patient_id="P1", age=70, sex="M", allergies=allergies or [])
    return SimpleNamespace(
        patient=patient,
        rng=None,  # any draw from the stay's stream would raise
        severity="severe",
        admission_time=ADMIT,
        disease_id="hemorrhagic_stroke",
        surgery=None,
        prior_procedures=[],
        encounter_id="E1",
        country_key=country,
        attending_id="DR1",
        protocol=load_disease_protocol("hemorrhagic_stroke"),
        department="internal_medicine",
        roster=None,
        child=None,
    )


def _run(orders=None):
    return SimpleNamespace(
        state=PhysiologicalState(),
        orders=orders or [],
        mars=[],
        lab_results=[],
        active_complications=set(),
        sustained={},
        complications=[],
        vitals=[],
        icu_transferred=False,
        icu_transferred_day=None,
        intubated_day=None,
        escalation_procedures=[],
        dvt_prophylaxis_planned=False,
    )


def _fire(monkeypatch, stay, run, name="aspiration_pneumonia", actions=("start_antibiotic", "NPO_or_NG_tube")):
    comp = {"name": name, "state_impact": {"inflammation_level": 0.2}, "actions": list(actions)}
    monkeypatch.setattr(dl, "evaluate_complications", lambda *a, **k: [comp])
    monkeypatch.setattr(dl, "_complication_context", lambda *a, **k: None)
    monkeypatch.setattr(
        dl, "_generate_mar", lambda patient, orders, *a, **k: [f"dose:{o.display_name}" for o in orders]
    )
    dl._apply_complications(stay, run, DAY, [comp])


def _antibiotic_orders(run):
    return [
        o
        for o in run.orders
        if o.order_type == OrderType.MEDICATION and "antibiotic" in drug_classes(o.drug_id or o.display_name)
    ]


def test_aspiration_pneumonia_gets_its_first_line_antibiotic_at_onset(monkeypatch) -> None:
    stay, run = _stay(), _run()
    _fire(monkeypatch, stay, run)
    orders = _antibiotic_orders(run)
    assert [o.display_name for o in orders] == ["Ampicillin/Sulbactam"]
    assert orders[0].status == OrderStatus.PLACED
    assert orders[0].ordered_datetime == (ADMIT + timedelta(days=DAY)).replace(hour=13, minute=0)
    assert run.mars  # the doses of the onset day are charted


def test_japan_uses_the_japan_first_line(monkeypatch) -> None:
    stay, run = _stay("japan"), _run()
    _fire(monkeypatch, stay, run, "urinary_tract_infection", ("start_antibiotics",))
    assert [o.display_name for o in _antibiotic_orders(run)] == ["Ceftriaxone"]


def test_a_running_antibiotic_of_the_same_drug_is_not_ordered_twice(monkeypatch) -> None:
    stay, run = _stay(), _run()
    _fire(monkeypatch, stay, run)
    before = len(run.orders)
    run.active_complications = set()
    _fire(monkeypatch, stay, run)
    assert len(_antibiotic_orders(run)) == 1
    assert len(run.orders) == before


def test_a_penicillin_allergy_does_not_get_a_penicillin(monkeypatch) -> None:
    from clinosim.types.allergy import Allergy

    penicillin = "764146007"  # SNOMED CT penicillin (substance), as used in the allergy tests
    stay = _stay(allergies=[Allergy(allergen_code=penicillin, category="medication")])
    run = _run()
    _fire(monkeypatch, stay, run)
    for o in _antibiotic_orders(run):
        assert "antibiotic.penicillin" not in drug_classes(o.drug_id or o.display_name)


def test_a_complication_without_a_named_regimen_orders_nothing(monkeypatch) -> None:
    stay, run = _stay(), _run()
    _fire(monkeypatch, stay, run, "intra_abdominal_abscess", ("percutaneous_drainage", "antibiotics"))
    assert not _antibiotic_orders(run)


def test_a_penicillin_allergy_gets_the_protocols_alternative(monkeypatch) -> None:
    from clinosim.types.allergy import Allergy

    stay = _stay(allergies=[Allergy(allergen_code="764146007", category="medication")])
    run = _run()
    _fire(monkeypatch, stay, run)
    assert stay.patient.safety_skip_log  # the penicillin was ruled out and logged
    given = [o.display_name for o in _antibiotic_orders(run)]
    assert given == ["Clindamycin"]  # the protocol's own penicillin-allergy alternative
