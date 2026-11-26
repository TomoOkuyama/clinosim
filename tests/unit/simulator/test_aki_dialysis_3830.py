"""Issue #3830: renal replacement therapy for AKI whose hyperkalemia or severe
metabolic acidosis persists. Intermittent hemodialysis sessions act on the
physiological state, so the derived potassium falls and the bicarbonate / total
CO2 rises after each session, and recur while the indication persists."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.simulator.renal_replacement import (
    decay_dialysis_clearance,
    renal_replacement_due,
    renal_replacement_rules,
    start_session,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import OrderResult

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 8, 0)


def _failing_kidneys() -> PhysiologicalState:
    return PhysiologicalState(renal_function=0.05, ph_status=-1.0)


def _labs(state: PhysiologicalState) -> dict[str, float]:
    return derive_lab_values(state, "M", 60)


def test_a_state_without_dialysis_derives_the_same_labs() -> None:
    state = _failing_kidneys()
    assert _labs(state) == _labs(replace(state, dialysis_clearance=0.0))
    assert _labs(state)["K"] >= 6.0 and _labs(state)["CO2"] <= 10.0


def test_a_session_lowers_potassium_and_creatinine_and_raises_bicarbonate() -> None:
    before = _labs(_failing_kidneys())
    state = _failing_kidneys()
    start_session(state)
    after = _labs(state)
    assert after["K"] < 5.5 < 6.0 <= before["K"]
    assert after["CO2"] > 10.0 > 0 and after["CO2"] > before["CO2"] + 5
    assert after["HCO3"] > before["HCO3"]
    assert after["Creatinine"] < before["Creatinine"]
    assert after["BUN"] < before["BUN"]


def test_the_effect_wears_off_over_the_days_after_a_session() -> None:
    state = _failing_kidneys()
    start_session(state)
    potassium = [_labs(state)["K"]]
    for _ in range(3):
        decay_dialysis_clearance(state)
        potassium.append(_labs(state)["K"])
    assert potassium == sorted(potassium)
    assert potassium[-1] > potassium[0] + 0.5


def _res(day: int, name: str, value: float) -> OrderResult:
    return OrderResult(result_datetime=_T0 + timedelta(days=day), lab_name=name, value=value)


def test_a_session_is_due_only_once_the_indication_persisted_past_the_medical_response() -> None:
    state = _failing_kidneys()
    today = [_res(1, "K", 6.6)]
    assert not renal_replacement_due(today, state, day=0, first_indication_day=0)
    assert renal_replacement_due(today, state, day=1, first_indication_day=0)
    assert not renal_replacement_due([_res(1, "K", 5.4), _res(1, "CO2", 18.0)], state, day=1, first_indication_day=0)
    assert renal_replacement_due([_res(1, "CO2", 9.0)], state, day=1, first_indication_day=0)


def test_no_session_once_the_kidneys_have_recovered() -> None:
    recovered = PhysiologicalState(renal_function=renal_replacement_rules().renal_function_below + 0.1)
    assert not renal_replacement_due([_res(1, "K", 6.6)], recovered, day=1, first_indication_day=0)


def test_forced_severe_aki_stays_get_recurring_sessions_and_correct_labs() -> None:
    from clinosim.codes.hl7_encounter import DischargeDisposition
    from clinosim.simulator import run_forced
    from clinosim.types.config import ForcedScenario, SimulatorConfig

    stays = fell = pairs = last_ok = 0
    for country in ("US", "JP"):
        scenario = ForcedScenario(
            disease_id="acute_kidney_injury", count=3, severity="severe", archetype="treatment_resistant"
        )
        for patient in run_forced(scenario, SimulatorConfig(random_seed=42, country=country)).patients:
            enc = patient.encounters[0]
            sessions = sorted(
                p.start_datetime
                for p in patient.procedures
                if p.encounter_id == enc.encounter_id and p.procedure_type == "dialysis_acute"
            )
            potassium = sorted((r.result_datetime, float(r.value)) for r in patient.lab_results if r.lab_name == "K")
            if enc.discharge_disposition == DischargeDisposition.EXP or not potassium:
                continue
            stays += 1
            assert len(sessions) >= 2, (country, len(sessions))
            for start in sessions:
                before = [v for t, v in potassium if t < start]
                nxt = [v for t, v in potassium if start < t <= start + timedelta(days=1)]
                if before and nxt:
                    pairs += 1
                    fell += nxt[0] < before[-1]
            last_ok += potassium[-1][1] < 6.0
            if potassium[-1][1] >= 6.0:
                assert enc.discharge_disposition != DischargeDisposition.HOME, (country, potassium[-1])
    assert stays >= 4
    # the potassium measurement is noisy: most, not every, post-session value is lower
    assert fell / pairs >= 0.7
    assert last_ok / stays >= 0.6
