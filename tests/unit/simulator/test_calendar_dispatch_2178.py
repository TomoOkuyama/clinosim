"""Calendar dispatch keeps every abortion / delivery record (Issue #2178)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import clinosim.simulator.engine as engine
import clinosim.simulator.perinatal as perinatal
from clinosim.modules.population.engine import LifeEvent
from clinosim.simulator.phases import _healthcare_calendar as hc

pytestmark = pytest.mark.unit


def _ctx() -> SimpleNamespace:
    person = SimpleNamespace(in_population_at=lambda _d: True)
    return SimpleNamespace(
        population=SimpleNamespace(get_person=lambda _pid: person),
        patient_records=[],
        patient_cache={},
        master_seed=1,
        demo={},
        roster=None,
        hospital_ops={},
        config=SimpleNamespace(country="US"),
        followup_data={},
    )


def _event(kind: str) -> LifeEvent:
    return LifeEvent(person_id="P1", event_type=kind, timestamp=date(2025, 5, 2), disease_id="O03.9")


@pytest.fixture(autouse=True)
def _no_activation(monkeypatch):
    monkeypatch.setattr(hc, "_activate_cached_person", lambda person, **_k: SimpleNamespace(patient_id="P1"))


def test_merged_abortion_does_not_raise(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(perinatal, "simulate_abortion_encounter", lambda **_k: ["ABORTION"])
    monkeypatch.setattr(engine, "_handle_overlap_via_merge", lambda *_a, **_k: "merged-into-stay")
    hc.dispatch_calendar_event(_event("abortion"), ctx)
    assert ctx.patient_records == []


def test_delivery_appends_every_companion(monkeypatch) -> None:
    ctx = _ctx()
    monkeypatch.setattr(perinatal, "simulate_delivery_encounter", lambda **_k: ["MOTHER", "BABY-1", "BABY-2"])
    monkeypatch.setattr(engine, "_handle_overlap_via_merge", lambda *_a, **_k: None)
    hc.dispatch_calendar_event(_event("delivery"), ctx)
    assert ctx.patient_records == ["MOTHER", "BABY-1", "BABY-2"]
