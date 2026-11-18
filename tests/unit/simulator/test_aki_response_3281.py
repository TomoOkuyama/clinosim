"""Issue #3281: nephrotoxic and renally cleared drugs are held while the
creatinine meets the KDIGO AKI definition, and a patient whose AKI is not
recovering, or who is febrile, is not discharge-ready."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pytest

from clinosim.codes.drugs import drug_key
from clinosim.codes.hl7_encounter import DischargeDisposition
from clinosim.modules.disease.protocol import load_disease_protocol
from clinosim.simulator.aki_response import (
    aki_course,
    aki_response_rules,
    discharge_findings_unresolved,
    fever_persists,
    holds_for_aki,
)
from clinosim.simulator.discharge_gate import _check_discharge_ready, discharge_disposition_for
from clinosim.simulator.discharge_rx import build_discharge_rx
from clinosim.simulator.medication_pipeline import _generate_mar
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType, VitalSignRecord
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_T0 = datetime(2026, 3, 1, 8, 0)


class _Roster:
    members: list = []

    def get_by_role(self, role: str, department: str | None = None) -> list:
        return []


def _cr(day: int, value: float) -> OrderResult:
    return OrderResult(result_datetime=_T0 + timedelta(days=day), lab_name="Creatinine", value=value)


def _temp(hours: float, c: float) -> VitalSignRecord:
    return VitalSignRecord(timestamp=_T0 + timedelta(hours=hours), temperature_celsius=c)


def test_kdigo_definition_ratio_and_absolute_rise() -> None:
    assert not aki_course([_cr(0, 0.8), _cr(1, 0.9)]).active
    assert aki_course([_cr(0, 0.8), _cr(1, 1.2)]).active  # 1.5 x baseline
    assert aki_course([_cr(0, 1.8), _cr(1, 2.1)]).active  # +0.3 mg/dL within 48 h
    assert not aki_course([_cr(0, 1.8), _cr(1, 1.95)]).active


def test_aki_resolves_when_creatinine_returns_below_the_definition() -> None:
    course = aki_course([_cr(0, 0.8), _cr(1, 2.0), _cr(3, 1.0)])
    assert course.active_at(_T0 + timedelta(days=2))
    assert not course.active


def test_not_improving_means_active_and_not_falling() -> None:
    assert aki_course([_cr(0, 0.8), _cr(1, 1.5), _cr(2, 2.0)]).not_improving
    assert not aki_course([_cr(0, 0.8), _cr(1, 2.0), _cr(2, 1.7)]).not_improving
    assert not aki_course([_cr(0, 0.8), _cr(1, 0.9)]).not_improving
    # a plateau high above baseline that has not fallen 10% from its peak
    assert aki_course([_cr(0, 1.35), _cr(5, 2.9), _cr(9, 3.55), _cr(10, 3.4)]).not_improving


def test_fever_window() -> None:
    assert fever_persists([_temp(0, 37.0), _temp(8, 38.4)])
    assert not fever_persists([_temp(0, 39.0), _temp(30, 37.2), _temp(36, 37.0)])
    assert not fever_persists([])


def test_gate_defers_discharge_for_findings() -> None:
    state = PhysiologicalState()
    assert _check_discharge_ready(state, 5, "us")
    assert not _check_discharge_ready(state, 5, "us", findings_unresolved=True)
    assert discharge_disposition_for(state, {}, died=False) == DischargeDisposition.HOME
    bad = aki_course([_cr(0, 0.8), _cr(1, 1.5), _cr(2, 2.0)])
    assert discharge_findings_unresolved(bad, [])
    assert discharge_findings_unresolved(aki_course([]), [_temp(0, 38.5)])
    assert not discharge_findings_unresolved(aki_course([_cr(0, 0.8)]), [_temp(0, 37.0)])


def test_hold_scope() -> None:
    for held in (
        "Ibuprofen",
        "Celecoxib 200mg",
        "Candesartan",
        "Lisinopril",
        "Hydrochlorothiazide",
        "Spironolactone",
        "Metformin",
    ):
        assert holds_for_aki(held), held
    for kept in ("Aspirin 100mg", "Furosemide", "Amlodipine", "Acetaminophen"):
        assert not holds_for_aki(kept), kept


def _order(oid: str, drug: str) -> Order:
    return Order(
        order_id=oid,
        encounter_id="ENC-3281",
        patient_id="POP-3281",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        ordered_datetime=_T0,
        status=OrderStatus.PLACED,
        route="PO",
        frequency_per_day=1,
    )


def test_mar_holds_doses_only_while_aki_is_active() -> None:
    orders = [_order("O-MET", "Metformin 500mg PO daily"), _order("O-AML", "Amlodipine 5mg PO daily")]
    course = aki_course([_cr(0, 0.8), _cr(1, 2.0), _cr(3, 0.9)])
    reason = aki_response_rules().reason

    def mar(day: int):
        return _generate_mar(
            PatientProfile(patient_id="POP-3281"),
            orders,
            day,
            _T0,
            roster=_Roster(),  # type: ignore[arg-type]
            rng=np.random.default_rng(0),
            aki=course,
        )

    held_day2 = {m.drug_name: m for m in mar(2)}
    metformin = next(m for n, m in held_day2.items() if "Metformin" in n)
    amlodipine = next(m for n, m in held_day2.items() if "Amlodipine" in n)
    assert metformin.status == "held" and metformin.hold_reason == reason
    assert amlodipine.status != "held"
    assert all(m.hold_reason != reason for m in mar(3))


def _discharge(patient: PatientProfile, aki_active: bool) -> tuple[list[str], list[str]]:
    protocol = load_disease_protocol("heart_failure_exacerbation")
    rx = build_discharge_rx(
        patient,
        "heart_failure_exacerbation",
        protocol,
        "PR-1",
        datetime(2026, 1, 1),
        np.random.default_rng(1),
        country_key="us",
        final_renal_function=0.9,
        aki_active=aki_active,
    )
    on_rx = [drug_key(i["drug_name"]) for i in rx.items]
    held = [drug_key(e.candidate_drug) for e in patient.safety_skip_log if e.event_type == "hold"]
    return on_rx, held


def test_discharge_holds_renal_risk_drugs_during_aki_and_restarts_after(patient_factory) -> None:
    on_rx, held = _discharge(
        patient_factory(current_meds=["Metformin", "Celecoxib", "Candesartan", "Amlodipine"]), True
    )
    assert not {"metformin", "celecoxib", "candesartan"} & set(on_rx)
    assert {"metformin", "celecoxib", "candesartan"} <= set(held)
    assert "amlodipine" in on_rx
    on_rx, held = _discharge(patient_factory(current_meds=["Metformin", "Celecoxib"]), False)
    assert {"metformin", "celecoxib"} <= set(on_rx)
    assert not held


def test_prn_nsaid_is_not_given_while_aki_is_active() -> None:
    from clinosim.simulator.medication_pipeline import generate_prn_administrations

    order = _order("O-PRN", "Diclofenac 25mg PO PRN")
    order.frequency = "PRN"
    vitals = [VitalSignRecord(timestamp=_T0 + timedelta(days=2), pain_score=7)]
    course = aki_course([_cr(0, 0.8), _cr(1, 2.0)])
    assert generate_prn_administrations([order], vitals, PhysiologicalState(), {}, course) == []
    assert generate_prn_administrations([order], vitals, PhysiologicalState(), {}, aki_course([_cr(0, 0.8)]))


def _instruction_ctx(creatinine: list[float], lang: str):
    from types import SimpleNamespace

    labs = [
        {"result_datetime": (_T0 + timedelta(days=d)).isoformat(), "lab_name": "Creatinine", "value": v}
        for d, v in enumerate(creatinine)
    ]
    return SimpleNamespace(
        patient=SimpleNamespace(sex="M", smoking_status="never", alcohol_use="none", chronic_conditions=[]),
        disease_protocol=None,
        diagnoses=[],
        discharge_medications=[],
        lab_results=labs,
        target_lang=lang,
        locale="jp" if lang == "ja" else "us",
    )


def test_discharge_instructions_add_a_creatinine_recheck_after_aki_only() -> None:
    from clinosim.modules.document.narrative.renderers._resolvers import resolve_discharge_instructions

    entry = resolve_discharge_instructions(_instruction_ctx([0.8, 1.5, 2.0], "en")).get("aki_recheck", {})
    assert "creatinine rechecked" in entry["en"] and "3 months" in entry["en"] and "restarted" in entry["en"]
    assert "再検査" in entry["ja"] and "再開しないで" in entry["ja"]
    assert "aki_recheck" not in resolve_discharge_instructions(_instruction_ctx([0.8, 0.9], "en"))
    assert "aki_recheck" not in resolve_discharge_instructions(_instruction_ctx([], "en"))
