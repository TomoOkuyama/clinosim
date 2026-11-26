"""A complication that lowers consciousness takes effect on the readings from
its onset, although the day's vitals were charted before it fired (Issue #3540)."""

from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from clinosim.simulator import daily_loop as dl
from clinosim.simulator.vitals_pipeline import lower_consciousness_from
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import VitalSignRecord

pytestmark = pytest.mark.unit

ADMIT = datetime(2026, 6, 18, 9, 0)
DAY = 8
NOON = (ADMIT + timedelta(days=DAY)).replace(hour=12, minute=0)


def _reading(hour: int, loc: str = "A", day: int = DAY) -> VitalSignRecord:
    t = (ADMIT + timedelta(days=day)).replace(hour=hour, minute=0)
    return VitalSignRecord(timestamp=t, heart_rate=90, consciousness_level=loc)


def _herniation_state() -> PhysiologicalState:
    return PhysiologicalState(consciousness_impairment=0.9)


def test_readings_from_the_onset_are_lowered_earlier_ones_are_not() -> None:
    vitals = [_reading(2), _reading(10), _reading(14), _reading(22), _reading(14, day=DAY + 1)]
    lower_consciousness_from(vitals, NOON, _herniation_state(), "hemorrhagic_stroke", "P1", DAY, "brain_herniation")
    assert [v.consciousness_level for v in vitals[:2]] == ["A", "A"]
    assert {v.consciousness_level for v in vitals[2:]} <= {"P", "U"}
    assert len({v.consciousness_level for v in vitals[2:]}) == 1  # day-stable


def test_a_reading_is_never_raised_and_empty_levels_stay_empty() -> None:
    vitals = [_reading(14, "U"), _reading(16, "")]
    lower_consciousness_from(vitals, NOON, PhysiologicalState(), "hemorrhagic_stroke", "P1", DAY, "x")
    assert [v.consciousness_level for v in vitals] == ["U", ""]


def test_apply_complications_lowers_the_same_day_readings(monkeypatch) -> None:
    herniation = {
        "name": "brain_herniation",
        "state_impact": {"consciousness_impairment": 0.55, "perfusion_status": -0.15},
        "actions": [],
    }
    monkeypatch.setattr(dl, "evaluate_complications", lambda *a, **k: [herniation])
    monkeypatch.setattr(dl, "_complication_context", lambda *a, **k: None)
    state = PhysiologicalState(consciousness_impairment=0.4)
    run = SimpleNamespace(
        state=state,
        orders=[],
        active_complications=set(),
        sustained={},
        complications=[],
        vitals=[_reading(2), _reading(14), _reading(22)],
        icu_transferred=False,
        icu_transferred_day=None,
        intubated_day=None,
        escalation_procedures=[],
        dvt_prophylaxis_planned=False,
    )
    stay = SimpleNamespace(
        patient=SimpleNamespace(patient_id="P1"),
        rng=None,
        severity="severe",
        admission_time=ADMIT,
        disease_id="hemorrhagic_stroke",
        surgery=None,
        prior_procedures=[],
    )
    dl._apply_complications(stay, run, DAY, [herniation])
    levels = [v.consciousness_level for v in run.vitals]
    assert levels[0] == "A"
    assert levels[1:] != ["A", "A"] and all(lv in ("P", "U") for lv in levels[1:])
