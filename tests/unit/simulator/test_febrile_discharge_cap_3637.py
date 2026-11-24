"""A patient still febrile at the extension cap is not released home (Issue #3637):
the fever has its own, longer cap, and a fever still present at that cap
discharges to a facility, with the discharge instructions saying so."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.simulator import aki_response as ar
from clinosim.simulator import run_forced
from clinosim.simulator.aki_response import (
    AkiCourse,
    aki_response_rules,
    discharge_extension_days,
)
from clinosim.simulator.discharge_gate import discharge_disposition_for
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.config import ForcedScenario, SimulatorConfig
from clinosim.types.encounter import VitalSignRecord

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 8, 0)


def _temp(hours: float, c: float) -> VitalSignRecord:
    return VitalSignRecord(timestamp=_T0 + timedelta(hours=hours), temperature_celsius=c)


def test_fever_cap_is_longer_than_the_kidney_cap() -> None:
    rules = aki_response_rules()
    assert rules.fever_max_extension_days > rules.max_extension_days


def test_extension_days_follow_the_unresolved_finding() -> None:
    rules = aki_response_rules()
    febrile, afebrile = [_temp(0, 39.5)], [_temp(0, 36.8)]
    assert discharge_extension_days(AkiCourse(), febrile) == rules.fever_max_extension_days
    assert discharge_extension_days(AkiCourse(), afebrile) == 0
    not_improving = AkiCourse(((_T0, 1.0, False), (_T0 + timedelta(days=1), 2.0, True)))
    assert discharge_extension_days(not_improving, afebrile) == rules.max_extension_days
    assert discharge_extension_days(not_improving, febrile) == rules.fever_max_extension_days


def test_unresolved_findings_are_not_released_home() -> None:
    state = PhysiologicalState()
    assert discharge_disposition_for(state, None, False) == DischargeDisposition.HOME
    assert discharge_disposition_for(state, None, False, findings_unresolved=True) == DischargeDisposition.SNF
    assert discharge_disposition_for(state, None, True, findings_unresolved=True) == DischargeDisposition.EXP


def _stay(monkeypatch: pytest.MonkeyPatch, febrile: bool):
    monkeypatch.setattr(ar, "fever_persists", lambda vitals: febrile)
    scenario = ForcedScenario(disease_id="bacterial_pneumonia", count=1, severity="moderate")
    dataset = run_forced(scenario, SimulatorConfig(random_seed=42, country="US"))
    return dataset.patients[0]


def test_a_still_febrile_stay_runs_past_the_old_cap_and_is_not_home(monkeypatch: pytest.MonkeyPatch) -> None:
    febrile = _stay(monkeypatch, True)
    enc = febrile.encounters[0]
    los = (enc.discharge_datetime - enc.admission_datetime).days
    assert enc.discharge_disposition != DischargeDisposition.HOME
    assert los > aki_response_rules().max_extension_days + 3


def test_an_afebrile_course_ends_at_the_sampled_stay(monkeypatch: pytest.MonkeyPatch) -> None:
    afebrile = _stay(monkeypatch, False)
    enc = afebrile.encounters[0]
    assert (enc.discharge_datetime - enc.admission_datetime).days <= 14


def _ctx(temps: list[float]):
    from types import SimpleNamespace

    vitals = [
        {"timestamp": (_T0 + timedelta(hours=6 * i)).isoformat(), "temperature_celsius": t} for i, t in enumerate(temps)
    ]
    return SimpleNamespace(
        patient=SimpleNamespace(sex="M", smoking_status="never", alcohol_use="none", chronic_conditions=[]),
        disease_protocol=None,
        diagnoses=[],
        discharge_medications=[],
        lab_results=[],
        vitals=vitals,
        target_lang="en",
        locale="us",
    )


def test_discharge_instructions_name_an_unresolved_fever_only() -> None:
    from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions

    entry = resolve_discharge_instructions(_ctx([38.9, 39.4])).get("fever_followup", {})
    assert "still had a fever" in entry["en"] and "発熱" in entry["ja"]
    assert "fever_followup" not in resolve_discharge_instructions(_ctx([38.9, 37.0, 36.9, 36.8, 36.9]))
    assert "fever_followup" not in resolve_discharge_instructions(_ctx([]))
