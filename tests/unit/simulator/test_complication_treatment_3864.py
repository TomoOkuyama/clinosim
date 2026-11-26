"""Issue #3864 (anticoagulation, anticoagulant hold, IV PPI): the treatment a
complication declares is ordered, not only noted.

A deep vein thrombosis / pulmonary embolism gets therapeutic anticoagulation
(and the discharge prescription carries it), a gastrointestinal bleed stops the
running anticoagulant and starts the declared IV proton pump inhibitor.
"""

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
    canonical_action,
    complication_action_rules,
    hold_actions_of,
    renal_decision,
    treatment_actions_of,
)
from clinosim.types.clinical import PhysiologicalState
from clinosim.types.encounter import Order, OrderResult, OrderStatus, OrderType
from clinosim.types.patient import PatientProfile

pytestmark = pytest.mark.unit

_DISEASES = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
ADMIT = datetime(2026, 6, 18, 9, 0)
DAY = 4
ONSET_ORDER = (ADMIT + timedelta(days=DAY)).replace(hour=13, minute=0)


def _complications() -> list[tuple[str, dict]]:
    return [
        (path.stem, comp)
        for path in sorted(_DISEASES.glob("*.yaml"))
        for comp in load_data_yaml(path).get("complications") or []
    ]


def _treatment_like(action: str) -> bool:
    low = action.lower()
    return "anticoag" in low or "ppi" in low


def test_every_anticoagulation_or_ppi_action_is_executed_or_listed() -> None:
    rules = complication_action_rules()
    executed = set(rules.treatment_actions) | set(rules.hold_actions)
    known = executed | set(rules.not_executed_treatment_actions)
    assert executed.isdisjoint(rules.not_executed_treatment_actions)
    for disease, comp in _complications():
        for action in comp.get("actions") or []:
            if isinstance(action, str) and _treatment_like(action):
                assert action in known, f"{disease}/{comp['name']}: unknown treatment action {action!r}"
                assert canonical_action(action) == action, f"{disease}/{comp['name']}: write the canonical key"


def test_the_regimen_protocols_have_a_regimen_for_both_countries() -> None:
    rules = complication_action_rules()
    for action, spec in rules.treatment_actions.items():
        drugs = load_disease_protocol(spec.protocol).drugs
        for country in ("us", "japan"):
            entries = [
                e
                for e in drugs[spec.block][country]
                if spec.drug_class in drug_classes(e.get("drug_id", "")) and spec.route in (None, e.get("route"))
            ]
            assert entries, f"{action}: {spec.protocol}.{spec.block}.{country} has no {spec.drug_class} entry"


def test_action_selection() -> None:
    assert treatment_actions_of({"actions": ["start_anticoagulation", "icu_transfer"]}) == ["start_anticoagulation"]
    assert treatment_actions_of({"actions": ["start_anticoagulation_cautiously"]}) == []
    assert treatment_actions_of({"actions": ["hold_anticoagulation", "IV_PPI"]}) == ["IV_PPI"]
    assert hold_actions_of({"actions": ["hold_anticoagulation", "IV_PPI"]}) == ["hold_anticoagulation"]
    assert hold_actions_of({"actions": ["reassess_antiplatelet"]}) == []


def test_renal_decision_reads_the_entry_thresholds() -> None:
    adj = {"eGFR_below_30": "avoid"}
    assert renal_decision(adj, 25.0) == "avoid" and renal_decision(adj, 45.0) is None
    assert renal_decision(adj, None) is None
    jp = {"eGFR_15_50": "30mg PO daily", "eGFR_below_15": "avoid"}
    assert renal_decision(jp, 10.0) == "avoid" and renal_decision(jp, 40.0) == "30mg PO daily"
    assert renal_decision(jp, 80.0) is None and renal_decision({}, 5.0) is None


def _stay(country: str = "us", allergies=None):
    patient = PatientProfile(
        patient_id="P1",
        age=70,
        sex="M",
        allergies=allergies or [],
        weight_kg=70.0,
        height_cm=170.0,
    )
    return SimpleNamespace(
        patient=patient,
        rng=None,  # any draw from the stay's stream would raise
        severity="moderate",
        admission_time=ADMIT,
        disease_id="bacterial_pneumonia",
        surgery=None,
        prior_procedures=[],
        encounter_id="E1",
        country_key=country,
        attending_id="DR1",
        protocol=load_disease_protocol("bacterial_pneumonia"),
        department="internal_medicine",
        roster=None,
        child=None,
    )


def _run(orders=None, creatinine=None, prophylaxis=False):
    results = []
    if creatinine is not None:
        results.append(
            OrderResult(
                result_datetime=ADMIT + timedelta(hours=1),
                performed_by="T",
                lab_name="Creatinine",
                value=creatinine,
                unit="mg/dL",
                flag="",
            )
        )
    return SimpleNamespace(
        state=PhysiologicalState(),
        orders=orders or [],
        mars=[],
        lab_results=results,
        active_complications=set(),
        sustained={},
        complications=[],
        vitals=[],
        icu_transferred=False,
        icu_transferred_day=None,
        intubated_day=None,
        escalation_procedures=[],
        dvt_prophylaxis_planned=prophylaxis,
    )


@pytest.fixture(autouse=True)
def _weight(monkeypatch):
    monkeypatch.setattr(
        "clinosim.modules.population.encounter_anthropometry.encounter_weight_kg",
        lambda patient, *args, **kwargs: patient.weight_kg,
    )


def _fire(monkeypatch, stay, run, name="dvt", actions=("start_anticoagulation",)):
    comp = {"name": name, "state_impact": {}, "actions": list(actions)}
    monkeypatch.setattr(dl, "evaluate_complications", lambda *a, **k: [comp])
    monkeypatch.setattr(dl, "_complication_context", lambda *a, **k: None)
    monkeypatch.setattr(
        dl,
        "_generate_mar",
        lambda patient, orders, *a, **k: [
            SimpleNamespace(order_id=o.order_id, scheduled_datetime=ONSET_ORDER)
            for o in orders
            if not o.administer_from
        ],
    )
    dl._apply_complications(stay, run, DAY, [comp])


def _meds(run, cls):
    return [
        o
        for o in run.orders
        if o.order_type == OrderType.MEDICATION
        and not o.display_name.startswith("DISCONTINUE:")
        and cls in drug_classes(o.drug_id or o.display_name)
    ]


def _given(run, order):
    return [m for m in run.mars if m.order_id == order.order_id]


def test_a_dvt_in_the_us_gets_the_protocols_oral_anticoagulant_at_onset(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run)
    (order,) = _meds(run, "anticoagulant")
    assert order.drug_id == "rivaroxaban" and order.status == OrderStatus.PLACED
    assert (order.dose_quantity, order.dose_unit, order.frequency_per_day) == (15.0, "mg", 2)
    assert order.ordered_datetime == ONSET_ORDER and order.route == "PO"
    assert order.renal_crcl_ml_min is not None
    assert _given(run, order), "the doses of the onset day are charted"


def test_a_dvt_in_japan_gets_heparin_for_five_days_then_edoxaban(monkeypatch) -> None:
    stay, run = _stay("japan"), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run)
    bolus, infusion, oral = _meds(run, "anticoagulant")
    assert (bolus.drug_id, bolus.single_dose, bolus.dose_unit) == ("heparin", True, "U/kg")
    assert (infusion.frequency, infusion.dose_unit, infusion.duration_days) == ("CONTINUOUS", "U/kg/h", 5)
    # "60mg PO daily (after 5+ days heparin)": ordered with the heparin, given from the fifth day on
    assert (oral.drug_id, oral.dose_quantity, oral.route) == ("edoxaban", 60.0, "PO")
    assert oral.administer_from == ONSET_ORDER + timedelta(days=5)
    assert not _given(run, oral)


def test_the_japan_edoxaban_dose_follows_the_renal_adjustment(monkeypatch) -> None:
    stay, run = _stay("japan"), _run(creatinine=2.0)  # CrCl about 36 mL/min: eGFR_15_50 gives 30 mg
    _fire(monkeypatch, stay, run)
    oral = [o for o in _meds(run, "anticoagulant") if o.drug_id == "edoxaban"]
    assert [(o.dose_quantity, o.dose_unit) for o in oral] == [(30.0, "mg")]
    stay2, run2 = _stay("japan"), _run(creatinine=6.0)  # CrCl about 12 mL/min: edoxaban is avoided
    _fire(monkeypatch, stay2, run2)
    assert {o.drug_id for o in _meds(run2, "anticoagulant")} == {"heparin"}


def test_severe_renal_impairment_moves_to_the_next_agent_of_the_protocol(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=4.5)  # CrCl about 14 mL/min: rivaroxaban is avoided below 30
    _fire(monkeypatch, stay, run)
    assert {o.drug_id for o in _meds(run, "anticoagulant")} == {"heparin"}


def test_a_running_therapeutic_anticoagulant_is_not_doubled(monkeypatch) -> None:
    stay = _stay()
    home = Order(
        order_id="ORD-E1-HM-01",
        order_type=OrderType.MEDICATION,
        display_name="Apixaban",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        dose_quantity=5.0,
        dose_unit="mg",
        frequency="BID",
    )
    run = _run([home], creatinine=0.9)
    _fire(monkeypatch, stay, run)
    assert [o.order_id for o in _meds(run, "anticoagulant")] == ["ORD-E1-HM-01"]


def test_no_anticoagulant_is_started_while_a_bleed_is_active(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    run.active_complications = {"gi_bleeding"}
    _fire(monkeypatch, stay, run)
    assert not _meds(run, "anticoagulant")


def test_the_staff_draw_uses_its_own_seed_not_the_stays_stream(monkeypatch) -> None:
    from clinosim.seeding import complication_treatment_seed

    assert complication_treatment_seed("E1", 4, "dvt", "start_anticoagulation") != complication_treatment_seed(
        "E1", 4, "dvt", "iv_ppi"
    )
    stay, run = _stay(), _run(creatinine=0.9)  # stay.rng is None: a draw would raise
    _fire(monkeypatch, stay, run)


def _running_enoxaparin() -> Order:
    return Order(
        order_id="ORD-E1-HM-02",
        order_type=OrderType.MEDICATION,
        display_name="Enoxaparin",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        dose_quantity=30.0,
        dose_unit="mg",
        frequency="DAILY",
        frequency_per_day=1,
        route="SC",
    )


def test_a_gi_bleed_orders_the_iv_ppi_and_a_stop_marker_for_each_running_anticoagulant(monkeypatch) -> None:
    from clinosim.modules._shared import COMPLICATION_HOLD_ORDER_ID_MARKER, MED_STOP_ORDER_ID_MARKER

    stay = _stay()
    order = _running_enoxaparin()
    run = _run([order], creatinine=0.9, prophylaxis=True)
    _fire(monkeypatch, stay, run, "gi_bleeding", ("hold_anticoagulation", "IV_PPI", "GI_consult"))
    bolus, infusion = _meds(run, "ppi")
    assert (bolus.drug_id, bolus.single_dose, bolus.route) == ("pantoprazole", True, "IV")
    assert (infusion.frequency, infusion.duration_days) == ("CONTINUOUS", 3)
    stops = [o for o in run.orders if o.display_name.startswith("DISCONTINUE:")]
    # the running order and the planned VTE prophylaxis (the same drug here: one marker per drug)
    assert [o.display_name for o in stops] == ["DISCONTINUE: Enoxaparin"]
    assert all(
        MED_STOP_ORDER_ID_MARKER in o.order_id and COMPLICATION_HOLD_ORDER_ID_MARKER in o.order_id for o in stops
    )
    assert stops[0].ordered_datetime == ONSET_ORDER
    assert dl._running_order(run.orders, "enoxaparin") is None


def test_the_prophylaxis_drug_is_stopped_when_a_bleed_holds_it(monkeypatch) -> None:
    stay, run = _stay("japan"), _run(creatinine=0.9, prophylaxis=True)
    _fire(monkeypatch, stay, run, "gi_bleeding", ("hold_anticoagulation",))
    assert [o.display_name for o in run.orders if o.display_name.startswith("DISCONTINUE:")] == [
        "DISCONTINUE: Heparin"
    ]  # the JP prophylaxis regimen (heparin 5,000 IU SC)


def test_doses_after_the_hold_are_dropped_after_the_stay() -> None:
    from clinosim.modules._shared import COMPLICATION_HOLD_ORDER_ID_MARKER, MED_STOP_ORDER_ID_MARKER
    from clinosim.modules.order.supersede import drop_doses_after_hold

    order = _running_enoxaparin()
    marker = Order(
        order_id=f"ORD-E1{MED_STOP_ORDER_ID_MARKER}D4{COMPLICATION_HOLD_ORDER_ID_MARKER}0-enoxapar",
        order_type=OrderType.MEDICATION,
        display_name="DISCONTINUE: Enoxaparin",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
    )
    before = SimpleNamespace(order_id=order.order_id, scheduled_datetime=ONSET_ORDER - timedelta(hours=4))
    after = SimpleNamespace(order_id=order.order_id, scheduled_datetime=ONSET_ORDER + timedelta(hours=8))
    other = SimpleNamespace(order_id="ORD-E1-HM-09", scheduled_datetime=ONSET_ORDER + timedelta(hours=8))
    kept = drop_doses_after_hold([order, marker], [before, after, other])
    assert kept == [before, other]
    assert order.end_datetime == ONSET_ORDER


def test_a_gi_bleed_with_no_anticoagulant_still_gets_the_ppi_and_stops_nothing(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "gi_bleeding", ("hold_anticoagulation", "IV_PPI"))
    assert _meds(run, "ppi") and not [o for o in run.orders if o.display_name.startswith("DISCONTINUE:")]


def test_the_protocol_hold_order_of_a_dvt_patient_stops_the_treatment_anticoagulant(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run)
    (treat,) = _meds(run, "anticoagulant")
    run.active_complications = set()
    _fire(monkeypatch, stay, run, "major_bleeding", ("hold_anticoagulation", "transfuse_if_needed"))
    assert dl._running_order(run.orders, "rivaroxaban") is None
    assert any(o.display_name == "DISCONTINUE: Rivaroxaban" for o in run.orders)


def test_discharge_carries_the_anticoagulant_started_for_the_complication(monkeypatch) -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs

    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run)
    (spec,) = complication_discharge_specs(run.orders, "us")
    assert spec["drug_id"] == "rivaroxaban" and spec.get("route", "PO") == "PO"
    assert spec["dose"] == "15mg PO BID x21 days, then 20mg PO daily"  # the course is not complete at discharge
    stay_jp, run_jp = _stay("japan"), _run(creatinine=0.9)
    _fire(monkeypatch, stay_jp, run_jp)
    (spec_jp,) = complication_discharge_specs(run_jp.orders, "japan")
    assert spec_jp["drug_id"] == "edoxaban" and spec_jp.get("route", "PO") == "PO"
    for o in run.orders:
        o.status = OrderStatus.STOPPED  # held for a bleed (the stop marker flips the status): nothing is continued
    assert complication_discharge_specs(run.orders, "us") == []


def test_the_discharge_prescription_lists_the_started_anticoagulant() -> None:
    import numpy as np

    from clinosim.simulator.discharge_rx import build_discharge_rx

    patient = PatientProfile(patient_id="P1", age=70, sex="M", weight_kg=70.0, height_cm=170.0)
    spec = {"drug_id": "rivaroxaban", "dose": "15mg PO BID x21 days, then 20mg PO daily", "route": "PO"}
    rx = build_discharge_rx(
        patient,
        "bacterial_pneumonia",
        load_disease_protocol("bacterial_pneumonia"),
        "DR1",
        ADMIT,
        np.random.default_rng(0),
        encounter_id="E1",
        country_key="us",
        extra_specs=[spec],
    )
    assert [i["drug_name"] for i in rx.items if i["drug_name"] == "Rivaroxaban"] == ["Rivaroxaban"]


def _record(orders, discharge_days=8):
    enc = SimpleNamespace(
        encounter_type="inpatient",
        admission_datetime=ADMIT,
        discharge_datetime=ADMIT + timedelta(days=discharge_days),
        encounter_id="E1",
        attending_physician_id="DR1",
    )
    patient = PatientProfile(patient_id="P1", age=70, sex="M", weight_kg=70.0, height_cm=170.0)
    return SimpleNamespace(encounters=[enc], orders=orders, patient=patient, results=[], lab_results=[])


def test_the_prophylaxis_runs_until_the_therapeutic_anticoagulant_starts() -> None:
    """The VTE prophylaxis of days 0-4 is not removed because a treatment
    anticoagulant is ordered on day 4: it ends at that order."""
    from clinosim.modules.prophylaxis.engine import build_dvt_prophylaxis_orders

    treat = Order(
        order_id="ORD-E1-COMPTX-D4-dvt-0",
        order_type=OrderType.MEDICATION,
        display_name="Rivaroxaban",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
        dose_quantity=15.0,
        dose_unit="mg",
        frequency="BID",
        frequency_per_day=2,
        route="PO",
    )
    (prophylaxis,) = build_dvt_prophylaxis_orders(record=_record([treat]), country="us")
    assert prophylaxis.ordered_datetime < ONSET_ORDER and prophylaxis.end_datetime == ONSET_ORDER
    # a therapeutic anticoagulant that is not a complication's still skips it, as before
    home = Order(
        order_id="ORD-E1-HM-01",
        order_type=OrderType.MEDICATION,
        display_name="Rivaroxaban",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
    )
    assert build_dvt_prophylaxis_orders(record=_record([home]), country="us") == []


def test_a_phased_regimen_is_given_as_its_first_phase_without_a_stop() -> None:
    from clinosim.modules.order.engine import parse_dose_string

    parsed = parse_dose_string("15mg PO BID x21 days, then 20mg PO daily")
    assert (parsed["dose_quantity"], parsed["dose_unit"], parsed["frequency"], parsed["frequency_per_day"]) == (
        15.0,
        "mg",
        "BID",
        2,
    )
    assert "duration_days" not in parsed  # the course continues with the later phase
    assert parse_dose_string("1g IV daily x5 days")["duration_days"] == 5


def test_the_complication_anticoagulant_replaces_an_antiplatelet_the_safety_rules_exclude() -> None:
    import numpy as np

    from clinosim.simulator.discharge_rx import build_discharge_rx

    patient = PatientProfile(patient_id="P1", age=70, sex="M", weight_kg=70.0, height_cm=170.0)
    cerebral = load_disease_protocol("cerebral_infarction")
    base = dict(country_key="japan", encounter_id="E1")
    plain = build_discharge_rx(patient, "cerebral_infarction", cerebral, "DR1", ADMIT, np.random.default_rng(0), **base)
    assert "Aspirin" in [i["drug_name"] for i in plain.items]
    spec = {"drug_id": "edoxaban", "dose": "60mg PO daily", "route": "PO"}
    rx = build_discharge_rx(
        patient, "cerebral_infarction", cerebral, "DR1", ADMIT, np.random.default_rng(0), extra_specs=[spec], **base
    )
    names = [i["drug_name"] for i in rx.items]
    assert "Edoxaban" in names and "Aspirin" not in names  # aspirin + DOAC is contraindicated (doac-plus-aspirin)
