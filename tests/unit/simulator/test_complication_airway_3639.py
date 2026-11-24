"""A complication that requires intubation is acted on (Issue #3639): the
airway is secured at its onset through the same path as the state-driven
intubation, the patient is ventilated and in the ICU, and the respiratory
failure is a coded diagnosis (through the in-hospital complication table of
Issue #3673). Non-invasive ventilation is a separate Issue."""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from clinosim.datafiles import load_data_yaml
from clinosim.simulator import daily_loop as dl
from clinosim.simulator.complication_actions import (
    airway_actions_of,
    complication_action_rules,
)
from clinosim.simulator.complication_dx import complication_diagnosis_code
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_DISEASES = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
ADMIT = datetime(2026, 6, 14, 10, 0)
DAY = 2
_AIRWAY_LIKE = re.compile(r"intubat|ventilat", re.I)


def _complications() -> list[tuple[str, dict]]:
    out = []
    for path in sorted(_DISEASES.glob("*.yaml")):
        for comp in load_data_yaml(path).get("complications") or []:
            out.append((path.stem, comp))
    return out


def test_intubation_actions_resolve_to_one_canonical_key() -> None:
    for action in ("intubation", "mechanical_ventilation", "intubation_mechanical_ventilation"):
        assert airway_actions_of({"actions": [action]}) == ["intubate"]
    assert airway_actions_of({"actions": ["intubation", "mechanical_ventilation"]}) == ["intubate"]
    assert airway_actions_of({"actions": ["icu_transfer", "sedation_protocol"]}) == []
    assert airway_actions_of({"actions": ["consider_intubation_if_severe"]}) == []
    assert airway_actions_of({}) == []


def test_every_airway_action_of_the_disease_yamls_is_executed_or_listed() -> None:
    rules = complication_action_rules()
    known = {a for a, canonical in rules.aliases.items() if canonical in rules.airway_actions}
    known |= set(rules.airway_actions) | set(rules.not_executed_airway_actions)
    for disease, comp in _complications():
        for action in comp.get("actions") or []:
            if isinstance(action, str) and _AIRWAY_LIKE.search(action):
                assert action in known, f"{disease}/{comp['name']}: unknown airway action {action!r}"


def test_respiratory_failure_complications_have_a_diagnosis_code() -> None:
    assert complication_diagnosis_code("respiratory_failure") == "J96.00"
    assert complication_diagnosis_code("respiratory_failure_requiring_niv") == "J96.00"
    assert complication_diagnosis_code("acute_respiratory_distress") == "J80"
    assert complication_diagnosis_code("ARDS") == "J80"


def _stay(age: int = 70, encounter_id: str = "ENC-1"):
    return SimpleNamespace(
        patient=PatientProfile(patient_id="P1", age=age, sex="M"),
        rng=None,  # any draw from the stay's stream would raise
        severity="severe",
        admission_time=ADMIT,
        disease_id="copd_exacerbation",
        surgery=None,
        prior_procedures=[],
        encounter_id=encounter_id,
        country="US",
        country_key="us",
        attending_id="DR1",
        child=None,
    )


def _run():
    return dl._Run(state=PhysiologicalState(), differential=None, orders=[], dvt_prophylaxis_planned=False)


def _fire(monkeypatch, stay, run, name="intubation_required", actions=("intubation", "icu_transfer")):
    comp = {"name": name, "state_impact": {"ph_status": -0.05}, "actions": list(actions)}
    monkeypatch.setattr(dl, "evaluate_complications", lambda *a, **k: [comp])
    monkeypatch.setattr(dl, "_complication_context", lambda *a, **k: None)
    dl._apply_complications(stay, run, DAY, [comp])


def test_intubation_complication_secures_the_airway_at_its_onset(monkeypatch) -> None:
    stay, run = _stay(), _run()
    monkeypatch.setattr(dl, "_airway_escalation_allowed", lambda s, r: True)
    _fire(monkeypatch, stay, run)
    onset = (ADMIT + timedelta(days=DAY)).replace(hour=12, minute=0, second=0, microsecond=0)
    assert run.intubated and run.intubated_day == DAY
    assert run.icu_transferred
    assert [p.procedure_code for p in run.escalation_procedures] and len(run.escalation_procedures) == 1
    assert run.escalation_procedures[0].start_datetime == onset
    assert run.oxygen.ventilated_since == onset
    assert any(o.display_name == "NPO" for o in run.orders)
    assert run.complications[0]["name"] == "intubation_required"


def test_an_already_intubated_patient_is_not_intubated_twice(monkeypatch) -> None:
    stay, run = _stay(), _run()
    monkeypatch.setattr(dl, "_airway_escalation_allowed", lambda s, r: True)
    _fire(monkeypatch, stay, run)
    _fire(monkeypatch, stay, run, "respiratory_failure", ("intubation", "mechanical_ventilation"))
    assert len(run.escalation_procedures) == 1


def test_a_patient_who_declined_intubation_is_not_intubated(monkeypatch) -> None:
    stay, run = _stay(), _run()
    monkeypatch.setattr(dl, "_airway_escalation_allowed", lambda s, r: False)
    _fire(monkeypatch, stay, run)
    assert not run.intubated and not run.escalation_procedures
    assert run.oxygen.ventilated_since is None


def test_a_complication_without_an_airway_action_is_unchanged(monkeypatch) -> None:
    stay, run = _stay(), _run()
    monkeypatch.setattr(dl, "_airway_escalation_allowed", lambda s, r: True)
    _fire(monkeypatch, stay, run, "pneumothorax", ("chest_tube_insertion", "icu_transfer"))
    assert not run.intubated and not run.escalation_procedures
    assert run.icu_transferred
