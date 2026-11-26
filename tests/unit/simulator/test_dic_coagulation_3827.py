"""A DIC complication shows in the coagulation labs and holds while sepsis lasts (Issue #3827)."""

from __future__ import annotations

import pytest

from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.modules.physiology.engine import derive_lab_values
from clinosim.simulator.sustained_complication import advance_holds, start_holds
from clinosim.types.clinical import PhysiologicalState


def _dic() -> dict:
    protocol = load_disease_protocol("sepsis")
    return next(c for c in protocol.complications if c["name"] == "disseminated_intravascular_coagulation")


def _holds(state: PhysiologicalState) -> dict:
    return {(("dic"), var): hold for var, hold in start_holds(_dic(), state).items()}


def _labs(state: PhysiologicalState) -> dict[str, float]:
    return derive_lab_values(state, age=60, sex="M")


def test_dic_complication_declares_sustained_coagulation_and_panel() -> None:
    dic = _dic()
    assert "coagulation_status" in dic["sustained_state"]
    assert "coagulation_status" not in dic.get("state_impact", {})
    assert dic["monitoring_labs"] == ["DIC_panel"]


def test_active_dic_shows_consumption_in_all_four_labs() -> None:
    before = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.15)
    base = _labs(before)
    state = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.15)
    holds = _holds(state)
    advance_holds(state, holds)
    labs = _labs(state)
    assert labs["Plt"] < 100  # ISTH: below 100 x10^3/uL scores
    assert labs["PT_INR"] > base["PT_INR"] + 0.8
    assert labs["Fibrinogen"] < base["Fibrinogen"] - 150
    assert labs["D_dimer"] > base["D_dimer"] + 1.0


def test_hold_fades_with_the_driver_and_is_dropped() -> None:
    state = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.1)
    holds = _holds(state)
    advance_holds(state, holds)
    peak = state.coagulation_status
    state.inflammation_level = 0.2
    for _ in range(2):  # full effect for the first days, whatever the driver does
        advance_holds(state, holds)
        assert state.coagulation_status == pytest.approx(peak)
    state.inflammation_level = 0.6
    advance_holds(state, holds)
    assert 0.1 < state.coagulation_status < peak
    state.inflammation_level = 0.2
    advance_holds(state, holds)
    assert state.coagulation_status == pytest.approx(0.1)
    assert holds == {}


def test_hold_keeps_the_courses_own_recovery() -> None:
    state = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.3)
    holds = _holds(state)
    advance_holds(state, holds)
    state.coagulation_status -= 0.2  # course recovery of the underlying state
    state.inflammation_level = 0.2
    for _ in range(4):
        advance_holds(state, holds)
    assert state.coagulation_status == pytest.approx(0.1, abs=1e-6)


def test_clamped_hold_does_not_over_release() -> None:
    state = PhysiologicalState(inflammation_level=0.9, coagulation_status=0.5)
    holds = _holds(state)
    advance_holds(state, holds)  # 0.5 + 0.85 clamps at 1.0, holds only 0.5
    state.inflammation_level = 0.1
    for _ in range(4):
        advance_holds(state, holds)
    assert state.coagulation_status == pytest.approx(0.5, abs=1e-6)


def test_every_sustained_state_and_monitoring_lab_in_the_disease_yaml_is_valid() -> None:
    from clinosim.modules.disease.protocol import load_all_disease_protocols
    from clinosim.modules.observation.order_routing import lab_order_targets
    from clinosim.modules.physiology.engine import canonical_state_vars
    from clinosim.simulator.sustained_complication import sustained_specs

    checked = 0
    for disease_id, protocol in load_all_disease_protocols().items():
        for comp in protocol.complications or []:
            for var, spec in sustained_specs(comp).items():
                assert var in canonical_state_vars()
                assert spec.driver in canonical_state_vars()
                checked += 1
            for lab in comp.get("monitoring_labs", []) or []:
                assert lab_order_targets(lab), f"{disease_id}: {lab}"
    assert checked >= 1
