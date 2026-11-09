"""Issue #2985: an in-hospital death follows a deteriorating course.

The day a death is drawn, the final hours before it carry a terminal state:
the last state-history entry worsens (perfusion, oxygenation, consciousness)
and the vitals recorded in the last 12 hours follow it, ending in a NEWS2
that calls for an emergency response.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, timedelta

import pytest

from clinosim.modules.observation.nursing import compute_news2
from clinosim.simulator.terminal_course import apply_terminal_course, terminal_state
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import VitalSignRecord
from clinosim.types.patient import BaselineVitals, PatientProfile

pytestmark = pytest.mark.unit

_ADMIT = datetime(2026, 3, 1, 14, 35)
_DEATH = datetime(2026, 3, 5, 0, 35)  # four days later at 00:mm, as the simulator sets it


def _patient() -> PatientProfile:
    p = PatientProfile(patient_id="POP-1")
    p.age = 74
    p.sex = "M"
    p.date_of_birth = date(1951, 6, 1)
    p.baseline_vitals = BaselineVitals(
        temperature=36.6, heart_rate=76, systolic_bp=128, diastolic_bp=76, respiratory_rate=16, spo2=97.0
    )
    return p


def _stable_vitals() -> list[VitalSignRecord]:
    out = []
    for day, hour in [(2, 10), (3, 6), (3, 14), (3, 18), (3, 22)]:
        out.append(
            VitalSignRecord(
                timestamp=_ADMIT.replace(hour=hour, minute=2) + timedelta(days=day),
                temperature_celsius=36.8,
                heart_rate=88,
                systolic_bp=124,
                diastolic_bp=74,
                respiratory_rate=17,
                spo2=96.0,
                pain_score=2,
                consciousness_level="A",
                nursing_note="improving, appetite good.",
                measured_by="NS-1",
            )
        )
    return out


def _calm(v: VitalSignRecord) -> bool:
    return (
        (v.spo2 is None or v.spo2 >= 92)
        and (v.heart_rate is None or v.heart_rate < 110)
        and (v.systolic_bp is None or v.systolic_bp >= 100)
    )


def _news2(v: VitalSignRecord) -> int:
    return compute_news2(
        {
            "respiratory_rate": v.respiratory_rate,
            "spo2": v.spo2,
            "on_supplemental_oxygen": v.on_supplemental_oxygen,
            "temperature_celsius": v.temperature_celsius,
            "systolic_bp": v.systolic_bp,
            "heart_rate": v.heart_rate,
            "consciousness_level": v.consciousness_level or "A",
        }
    )


def _run(state: PhysiologicalState | None = None):
    state = state or PhysiologicalState(inflammation_level=0.2, perfusion_status=0.95)
    history = [PhysiologicalState(inflammation_level=0.6), deepcopy(state)]
    vitals = _stable_vitals()
    apply_terminal_course(
        vitals,
        history,
        _patient(),
        disease_id="pneumonia",
        encounter_id="ENC-1",
        death_time=_DEATH,
    )
    return vitals, history


def test_a_death_encounters_state_history_worsens_before_death() -> None:
    day_state = PhysiologicalState(inflammation_level=0.2, perfusion_status=0.95)
    _, history = _run(day_state)
    last = history[-1]
    for before in (history[-2], day_state):
        assert last.perfusion_status < before.perfusion_status
        assert last.oxygenation_impairment > before.oxygenation_impairment
        assert last.consciousness_impairment > before.consciousness_impairment
    assert last.inflammation_level == day_state.inflammation_level  # labs keep their day's value


def test_the_last_12_hours_are_not_calm_and_end_in_an_emergency_news2() -> None:
    vitals, _ = _run()
    window = [v for v in vitals if _DEATH - timedelta(hours=12) <= v.timestamp < _DEATH]
    assert window and not all(_calm(v) for v in window)
    assert _news2(max(window, key=lambda v: v.timestamp)) >= 7
    assert vitals == sorted(vitals, key=lambda v: v.timestamp)
    assert not any("improving" in v.nursing_note for v in window)


def test_vitals_before_the_terminal_window_are_unchanged() -> None:
    vitals, _ = _run()
    early = [v for v in vitals if v.timestamp < _DEATH - timedelta(hours=12)]
    assert early == [v for v in _stable_vitals() if v.timestamp < _DEATH - timedelta(hours=12)]


def test_a_terminal_observation_is_charted_when_the_last_round_is_hours_earlier() -> None:
    vitals = [v for v in _stable_vitals() if v.timestamp.hour != 22]  # last round 18:02
    history = [PhysiologicalState(), PhysiologicalState()]
    apply_terminal_course(vitals, history, _patient(), disease_id="", encounter_id="ENC-1", death_time=_DEATH)
    last = vitals[-1]
    assert _DEATH - timedelta(hours=1) <= last.timestamp < _DEATH
    assert last.heart_rate is not None and last.spo2 is not None and last.consciousness_level
    assert last.measured_by == "NS-1"


def test_terminal_state_never_improves_an_already_worse_axis() -> None:
    worse = PhysiologicalState(perfusion_status=0.05, oxygenation_impairment=0.9, consciousness_impairment=1.0)
    t = terminal_state(worse)
    assert t.perfusion_status == 0.05 and t.oxygenation_impairment == 0.9 and t.consciousness_impairment == 1.0


def test_deterministic() -> None:
    assert _run()[0] == _run()[0]
