"""Issue #3896: the regimens a complication orders follow the severity and the
source (C. difficile), the IV PPI steps down to an oral one, and a held home
anticoagulant gets an explicit discharge decision.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from clinosim.simulator import daily_loop as dl
from clinosim.types.encounter import OrderResult, OrderStatus
from clinosim.types.patient import ChronicCondition
from tests.unit.simulator.test_complication_treatment_3864 import (  # noqa: F401
    _CDIFF,
    ADMIT,
    ONSET_ORDER,
    _fire,
    _given,
    _meds,
    _run,
    _stay,
    _weight,
)

pytestmark = pytest.mark.unit


def _lab(run, name: str, value: float, unit: str) -> None:
    run.lab_results.append(
        OrderResult(
            result_datetime=ADMIT + timedelta(days=4, hours=2),
            performed_by="T",
            lab_name=name,
            value=value,
            unit=unit,
            flag="",
        )
    )


def _cdiff(monkeypatch, country: str, wbc: float | None = None, creatinine: float = 0.9, age: int = 50, conditions=()):
    """A C. difficile onset; the default patient is under 65 without an immune disorder, so the
    regimen is the one of a first episode without recurrence risk."""
    stay, run = _stay(country), _run(creatinine=creatinine)
    stay.patient.age = age
    stay.patient.chronic_conditions = [ChronicCondition(code=c) for c in conditions]
    if wbc is not None:
        _lab(run, "WBC", wbc, "/uL")
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    return run


def _cdiff_orders(run):
    return [o for o in _meds(run, "antibiotic") if "-COMPTX-" in o.order_id]


def test_jp_non_severe_first_episode_gets_oral_metronidazole_500_mg_tid_for_10_days(monkeypatch) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=9000.0)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route, order.status) == ("metronidazole", "PO", OrderStatus.PLACED)
    assert (order.dose_quantity, order.dose_unit, order.frequency_per_day, order.duration_days) == (500.0, "mg", 3, 10)
    assert _given(run, order)


@pytest.mark.parametrize(("wbc", "creatinine"), [(15000.0, 0.9), (22000.0, 0.9), (9000.0, 1.6), (9000.0, 3.0)])
def test_jp_severe_cdi_gets_oral_vancomycin_125_mg_qid(monkeypatch, wbc, creatinine) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=wbc, creatinine=creatinine)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route) == ("vancomycin", "PO")
    assert (order.dose_quantity, order.frequency_per_day, order.duration_days) == (125.0, 4, 10)


@pytest.mark.parametrize(("wbc", "creatinine"), [(14999.0, 1.5), (None, 1.5), (None, 0.9)])
def test_jp_cdi_below_both_severity_limits_is_non_severe(monkeypatch, wbc, creatinine) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=wbc, creatinine=creatinine)
    assert [o.drug_id for o in _cdiff_orders(run)] == ["metronidazole"]


@pytest.mark.parametrize("wbc", [None, 9000.0, 20000.0])
def test_us_cdi_keeps_oral_vancomycin_whatever_the_severity(monkeypatch, wbc) -> None:
    run = _cdiff(monkeypatch, "us", wbc=wbc)
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route, order.dose_quantity, order.frequency_per_day) == ("vancomycin", "PO", 125.0, 4)


def test_the_severity_is_read_at_the_onset_not_from_a_later_result(monkeypatch) -> None:
    stay, run = _stay("japan"), _run(creatinine=0.9)
    stay.patient.age = 50
    run.lab_results.append(
        OrderResult(
            result_datetime=ONSET_ORDER + timedelta(days=2),
            performed_by="T",
            lab_name="WBC",
            value=30000.0,
            unit="/uL",
            flag="",
        )
    )
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    assert [o.drug_id for o in _cdiff_orders(run)] == ["metronidazole"]


def test_metronidazole_course_continues_at_discharge_and_is_not_held() -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs
    from clinosim.types.encounter import Order, OrderType

    order = Order(
        order_id="ORD-E1-COMPTX-D4-c_diff_colitis-0",
        order_type=OrderType.MEDICATION,
        display_name="Metronidazole",
        drug_id="metronidazole",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
        dose_quantity=500.0,
        dose_unit="mg",
        frequency="TID",
        frequency_per_day=3,
        route="PO",
        duration_days=10,
    )
    (spec,) = complication_discharge_specs([order], "japan", discharge_time=ONSET_ORDER + timedelta(days=4))
    assert (spec["drug_id"], spec["duration_days"], spec["from_complication"]) == ("metronidazole", 6, True)


def test_dl_module_still_exposes_the_loop() -> None:
    assert callable(dl._apply_complications)


def test_no_protocol_defines_a_lower_cdi_risk_alternative_so_the_stopped_antibiotic_is_not_replaced() -> None:
    """The stop of the inciting antibiotic orders a replacement only where the
    protocol authors a lower-risk alternative (``replacement_block``). No
    protocol does: when one adds the block this test fails, and the ordering of
    the replacement has to be implemented with it, not left silent."""
    from clinosim.simulator.complication_actions import complication_action_rules
    from tests.unit.simulator.test_complication_treatment_3864 import _complications  # noqa: F401

    block = complication_action_rules().stop_actions["stop_offending_antibiotic"].replacement_block
    assert block == "lower_cdi_risk_alternative"
    from pathlib import Path

    from clinosim.datafiles import load_data_yaml

    root = Path(__file__).resolve().parents[3] / "clinosim" / "modules" / "disease" / "reference_data"
    defining = [p.stem for p in sorted(root.glob("*.yaml")) if block in (load_data_yaml(p).get("drugs") or {})]
    assert defining == []


def test_the_stop_marker_says_no_replacement_antibiotic_is_ordered(monkeypatch) -> None:
    from clinosim.types.encounter import Order, OrderType

    stay = _stay()
    running = Order(
        order_id="ORD-E1-ADM-M02",
        order_type=OrderType.MEDICATION,
        display_name="Levofloxacin",
        drug_id="levofloxacin",
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        dose_quantity=750.0,
        dose_unit="mg",
        frequency="DAILY",
        frequency_per_day=1,
        route="IV",
    )
    run = _run([running], creatinine=0.9)
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    (marker,) = [o for o in run.orders if o.display_name == "DISCONTINUE: Levofloxacin"]
    assert "no replacement antibiotic" in marker.clinical_intent
    assert "代わりの抗菌薬は発注しない" in marker.clinical_intent_ja
    # the hold of an anticoagulant keeps its own wording
    assert "replacement" not in dl.t("order_intent.complication_anticoagulant_hold", "en", day=4, complication="x")


_GI = ("hold_anticoagulation", "IV_PPI", "GI_consult")


@pytest.mark.parametrize(("country", "drug", "dose"), [("us", "pantoprazole", 40.0), ("japan", "omeprazole", 20.0)])
def test_the_iv_ppi_steps_down_to_the_protocols_oral_ppi_after_the_iv_course(monkeypatch, country, drug, dose) -> None:
    stay, run = _stay(country), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "gi_bleeding", _GI)
    bolus, infusion, oral = _meds(run, "ppi")
    assert (bolus.drug_id, bolus.route, infusion.duration_days) == (drug, "IV", 3)
    assert (oral.drug_id, oral.route, oral.dose_quantity, oral.dose_unit, oral.frequency) == (
        drug,
        "PO",
        dose,
        "mg",
        "DAILY",
    )
    # given from the end of the 3-day IV course, until 2 weeks after the onset
    assert oral.administer_from == ONSET_ORDER + timedelta(days=3)
    assert oral.administer_from + timedelta(days=oral.duration_days) == ONSET_ORDER + timedelta(days=14)
    assert not _given(run, oral), "no oral dose is charted on the onset day"
    assert oral.status == OrderStatus.PLACED and "-COMPTX-" in oral.order_id


def test_the_oral_ppi_course_continues_at_discharge_for_the_rest_of_the_two_weeks(monkeypatch) -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs

    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "gi_bleeding", _GI)
    specs = complication_discharge_specs(run.orders, "us", discharge_time=ONSET_ORDER + timedelta(days=5))
    assert [(s["drug_id"], s["route"], s["duration_days"], s["from_complication"]) for s in specs] == [
        ("pantoprazole", "PO", 9, True)
    ]
    assert complication_discharge_specs(run.orders, "us", discharge_time=ONSET_ORDER + timedelta(days=14)) == []
    # discharged during the IV course: the oral course still ends 14 days after the onset
    early = complication_discharge_specs(run.orders, "us", discharge_time=ONSET_ORDER + timedelta(days=2))
    assert [s["duration_days"] for s in early] == [12]


def test_the_oral_step_down_is_not_ordered_without_a_ppi_course(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "major_bleeding", ("hold_anticoagulation",))
    assert not _meds(run, "ppi")


def test_the_oral_ppi_intent_says_oral_step_down(monkeypatch) -> None:
    stay, run = _stay(), _run(creatinine=0.9)
    _fire(monkeypatch, stay, run, "gi_bleeding", _GI)
    oral = _meds(run, "ppi")[-1]
    assert "oral proton pump inhibitor" in oral.clinical_intent and "経口" in oral.clinical_intent_ja


def test_a_step_down_must_follow_a_course() -> None:
    from pydantic import ValidationError

    from clinosim.simulator.complication_actions import TreatmentAction

    base = dict(protocol="gi_bleeding", block="first_line", drug_class="ppi", intent="complication_ppi")
    with pytest.raises(ValidationError):
        TreatmentAction(**base, step_down={"route": "PO", "total_days": 14})  # no IV course to follow
    with pytest.raises(ValidationError):
        TreatmentAction(**base, course_days=3, step_down={"route": "PO", "total_days": 3})


# --- held home anticoagulant: an explicit discharge decision (Issue #3896) ---


def _home_patient(*drugs: str):
    from clinosim.types.patient import PatientProfile

    return PatientProfile(
        patient_id="P1", age=70, sex="M", weight_kg=70.0, height_cm=170.0, current_medications=list(drugs)
    )


def _hold_marker(drug: str):
    from clinosim.modules._shared import COMPLICATION_HOLD_ORDER_ID_MARKER, MED_STOP_ORDER_ID_MARKER
    from clinosim.types.encounter import Order, OrderType

    return Order(
        order_id=f"ORD-E1{MED_STOP_ORDER_ID_MARKER}D4{COMPLICATION_HOLD_ORDER_ID_MARKER}0-{drug.lower()[:8]}",
        order_type=OrderType.MEDICATION,
        display_name=f"DISCONTINUE: {drug}",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
    )


def _rx(patient, held=(), final_renal=1.0, extra=()):
    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator.discharge_rx import build_discharge_rx

    return build_discharge_rx(
        patient,
        "bacterial_pneumonia",
        load_disease_protocol("bacterial_pneumonia"),
        "DR1",
        ADMIT,
        np.random.default_rng(0),
        encounter_id="E1",
        country_key="us",
        final_renal_function=final_renal,
        held_anticoagulants=held,
        extra_specs=extra,
    )


def test_the_held_home_anticoagulants_are_found_from_the_stop_markers_and_the_home_list() -> None:
    from clinosim.simulator.complication_actions import held_home_anticoagulants

    patient = _home_patient("Warfarin", "Atorvastatin")
    markers = [_hold_marker("Warfarin"), _hold_marker("Enoxaparin"), _hold_marker("Levofloxacin")]
    # enoxaparin was the stay's prophylaxis, levofloxacin is no anticoagulant: only the home one counts
    assert held_home_anticoagulants(markers, patient) == ["Warfarin"]
    assert held_home_anticoagulants([], patient) == []


def test_a_held_home_anticoagulant_is_resumed_at_discharge_and_the_item_says_so() -> None:
    patient = _home_patient("Warfarin")
    rx = _rx(patient, held=["Warfarin"])
    (item,) = [i for i in rx.items if i["drug_name"] == "Warfarin"]
    assert item["reconciliation"] == "resumed"
    assert not [i for i in rx.items if i["drug_name"] != "Warfarin" and "reconciliation" in i]
    assert "reconciliation" not in {k for i in _rx(patient).items for k in i}, "no hold, no decision"


def test_a_held_home_anticoagulant_that_a_discharge_rule_holds_is_stopped_and_logged() -> None:
    patient = _home_patient("Enoxaparin")  # a renal-hold drug at a kidney function below the discharge threshold
    rx = _rx(patient, held=["Enoxaparin"], final_renal=0.1)
    assert not [i for i in rx.items if i["drug_name"] == "Enoxaparin"]
    log = [e for e in patient.safety_skip_log if e.candidate_drug == "Enoxaparin" and e.event_type == "hold"]
    assert len(log) == 1


def test_a_held_anticoagulant_the_patient_does_not_take_at_home_states_nothing() -> None:
    other = _home_patient("Atorvastatin")
    rx = _rx(other, held=["Apixaban"])
    assert not other.safety_skip_log and not [i for i in rx.items if "reconciliation" in i]


def test_the_discharge_summary_says_the_held_anticoagulant_was_resumed() -> None:
    from types import SimpleNamespace

    from clinosim.modules.document.narrative._hospital_course import medication_changes_sentence

    home = [{"drug_name": "Warfarin", "dose": "3mg"}]
    discharge = [{"drug_name": "Warfarin", "dose": "3mg", "reconciliation": "resumed"}]
    for lang, expected in (("en", "resumed"), ("ja", "再開")):
        ctx = SimpleNamespace(target_lang=lang, home_medications_at_admission=home, discharge_medications=discharge)
        line, _ = medication_changes_sentence(ctx)
        assert expected in line and "Warfarin" in line or "ワルファリン" in line, line


# --- JP edoxaban against the PMDA package insert (Issue #3896) ---


def _edoxaban_orders(run):
    return [o for o in _meds(run, "anticoagulant") if o.drug_id == "edoxaban"]


def _dvt_japan(monkeypatch, *, weight=70.0, creatinine=0.9, home=()):
    from clinosim.types.patient import PatientProfile

    stay, run = _stay("japan"), _run(creatinine=creatinine)
    stay.patient = PatientProfile(
        patient_id="P1", age=70, sex="M", weight_kg=weight, height_cm=170.0, current_medications=list(home)
    )
    _fire(monkeypatch, stay, run)
    return stay, run


def test_edoxaban_is_60_mg_above_60_kg_and_30_mg_at_or_below_60_kg(monkeypatch) -> None:
    # PMDA insert, 6. 用法及び用量 (VTE): "体重60kg以下：30mg 体重60kg超：60mg"
    _, heavy = _dvt_japan(monkeypatch, weight=61.0)
    _, light = _dvt_japan(monkeypatch, weight=60.0)
    assert [o.dose_quantity for o in _edoxaban_orders(heavy)] == [60.0]
    assert [o.dose_quantity for o in _edoxaban_orders(light)] == [30.0]


@pytest.mark.parametrize("drug", ["Verapamil", "Erythromycin", "Cyclosporine"])
def test_edoxaban_is_30_mg_with_a_p_glycoprotein_inhibitor_the_insert_names(monkeypatch, drug) -> None:
    # 7.2: "キニジン硫酸塩水和物、ベラパミル塩酸塩、エリスロマイシン、シクロスポリン ... 本剤30mgを1日1回"
    _, run = _dvt_japan(monkeypatch, home=[drug])
    assert [o.dose_quantity for o in _edoxaban_orders(run)] == [30.0]


def test_edoxaban_renal_limits_follow_the_insert(monkeypatch) -> None:
    # 7.1: CLcr 30-50 -> 30 mg; 15-<30 -> 30 mg if given; 2.4 / 9.2.2: CLcr < 15 contraindicated
    _, moderate = _dvt_japan(monkeypatch, creatinine=1.9)  # CrCl about 38 mL/min for the test patient
    assert [o.dose_quantity for o in _edoxaban_orders(moderate)] == [30.0]
    _, severe = _dvt_japan(monkeypatch, creatinine=3.5)  # about 21 mL/min
    assert [o.dose_quantity for o in _edoxaban_orders(severe)] == [30.0]
    _, failure = _dvt_japan(monkeypatch, creatinine=6.0)  # about 12 mL/min
    assert _edoxaban_orders(failure) == []


def test_the_discharge_dose_of_edoxaban_follows_the_weight_and_the_renal_limit(monkeypatch) -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs

    def specs(run, weight, active=()):
        return complication_discharge_specs(
            run.orders, "japan", discharge_time=ONSET_ORDER + timedelta(days=8), weight_kg=weight, active_drugs=active
        )

    _, light = _dvt_japan(monkeypatch, weight=55.0)
    (spec,) = specs(light, 55.0)
    assert (spec["drug_id"], spec["dose"]) == ("edoxaban", "30mg PO daily")
    _, heavy = _dvt_japan(monkeypatch, weight=80.0)
    assert specs(heavy, 80.0)[0]["dose"] == "60mg PO daily"
    assert specs(heavy, 80.0, ["Verapamil"])[0]["dose"] == "30mg PO daily"
    _, renal = _dvt_japan(monkeypatch, weight=80.0, creatinine=1.9)
    assert specs(renal, 80.0)[0]["dose"] == "30mg PO daily"  # the protocol's discharge entry has the renal limits too


def test_the_dose_reduction_rule_is_validated_and_names_catalog_drugs() -> None:
    from clinosim.codes.drugs import get_drug
    from clinosim.simulator.complication_actions import complication_action_rules

    rule = complication_action_rules().dose_reductions["edoxaban"]
    assert rule.weight_kg_at_most == 60.0 and rule.dose == "30mg PO daily"
    assert all(get_drug(d) is not None for d in rule.interacting_drugs)


# --- the same edoxaban rule at the discharge of the pulmonary embolism / atrial fibrillation / stroke protocols ---


def _jp_discharge_edoxaban(disease: str, weight: float, home=()):
    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator.discharge_rx import build_discharge_rx
    from clinosim.types.patient import PatientProfile

    for seed in range(40):  # the protocols draw the anticoagulant (edoxaban 0.8 / 0.2 warfarin)
        patient = PatientProfile(
            patient_id="P1", age=70, sex="M", weight_kg=weight, height_cm=170.0, current_medications=list(home)
        )
        rx = build_discharge_rx(
            patient,
            disease,
            load_disease_protocol(disease),
            "DR1",
            ADMIT,
            np.random.default_rng(seed),
            encounter_id="E1",
            country_key="japan",
        )
        found = [i for i in rx.items if i["drug_name"] == "Edoxaban"]
        if found:
            return found[0]
    raise AssertionError(f"no edoxaban discharge item for {disease}")


@pytest.mark.parametrize("disease", ["pulmonary_embolism", "atrial_fibrillation_rvr"])
def test_the_edoxaban_discharge_dose_of_every_protocol_follows_the_weight_and_the_interactions(disease) -> None:
    light = _jp_discharge_edoxaban(disease, 55.0)
    assert light["dose"].startswith("30mg") and light["dose_ja"].startswith("30mg")
    assert _jp_discharge_edoxaban(disease, 80.0)["dose"].startswith("60mg")
    with_verapamil = _jp_discharge_edoxaban(disease, 80.0, home=["Verapamil"])
    assert with_verapamil["dose"].startswith("30mg")


# --- fidaxomicin for a first episode with recurrence risk, Japan (Issue #3896) ---


def _fidaxomicin_ok(run) -> None:
    (order,) = _cdiff_orders(run)
    assert (order.drug_id, order.route, order.status) == ("fidaxomicin", "PO", OrderStatus.PLACED)
    assert (order.dose_quantity, order.dose_unit, order.frequency_per_day, order.duration_days) == (200.0, "mg", 2, 10)
    assert _given(run, order)


@pytest.mark.parametrize("wbc", [9000.0, 16000.0])
def test_jp_first_episode_at_65_or_over_gets_fidaxomicin_whatever_the_severity(monkeypatch, wbc) -> None:
    _fidaxomicin_ok(_cdiff(monkeypatch, "japan", wbc=wbc, age=65))
    _fidaxomicin_ok(_cdiff(monkeypatch, "japan", wbc=wbc, age=88))


@pytest.mark.parametrize(("wbc", "drug"), [(9000.0, "metronidazole"), (16000.0, "vancomycin")])
def test_jp_first_episode_under_65_keeps_the_metronidazole_or_vancomycin_arm(monkeypatch, wbc, drug) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=wbc, age=64)
    assert [o.drug_id for o in _cdiff_orders(run)] == [drug]


@pytest.mark.parametrize("code", ["D80.0", "D84.9", "B20", "Z94.0"])
def test_jp_immunosuppressed_patient_under_65_gets_fidaxomicin(monkeypatch, code) -> None:
    _fidaxomicin_ok(_cdiff(monkeypatch, "japan", wbc=9000.0, age=40, conditions=[code]))
    _fidaxomicin_ok(_cdiff(monkeypatch, "japan", wbc=18000.0, age=40, conditions=[code]))


def test_a_condition_outside_the_immunosuppressed_group_is_no_recurrence_risk(monkeypatch) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=9000.0, age=40, conditions=["E11.9", "I10"])
    assert [o.drug_id for o in _cdiff_orders(run)] == ["metronidazole"]


def test_severity_alone_is_not_a_recurrence_risk(monkeypatch) -> None:
    run = _cdiff(monkeypatch, "japan", wbc=30000.0, creatinine=3.0, age=40)
    assert [o.drug_id for o in _cdiff_orders(run)] == ["vancomycin"]


@pytest.mark.parametrize("age", [30, 70, 90])
def test_us_keeps_oral_vancomycin_at_any_age(monkeypatch, age) -> None:
    run = _cdiff(monkeypatch, "us", wbc=9000.0, age=age, conditions=["D80.0"])
    assert [o.drug_id for o in _cdiff_orders(run)] == ["vancomycin"]


def test_the_age_comes_from_the_birth_date_at_admission_when_it_is_known(monkeypatch) -> None:
    from datetime import date

    stay, run = _stay("japan"), _run(creatinine=0.9)
    stay.patient.age = 30  # a stale field: the birth date decides
    stay.patient.date_of_birth = date(ADMIT.year - 66, 1, 1)
    _lab(run, "WBC", 9000.0, "/uL")
    _fire(monkeypatch, stay, run, "c_diff_colitis", _CDIFF)
    _fidaxomicin_ok(run)


def test_fidaxomicin_is_in_the_catalog_with_its_codes() -> None:
    from clinosim.codes.drugs import get_drug

    rec = get_drug("fidaxomicin")
    assert rec is not None and rec.codes["rxnorm"] == "1111103" and rec.codes["yj"] == "6119001F1025"
    assert rec.classes == ("antibiotic.macrocyclic",)


def test_the_fidaxomicin_course_continues_at_discharge_and_is_not_held() -> None:
    from clinosim.simulator.complication_actions import complication_discharge_specs
    from clinosim.types.encounter import Order, OrderType

    order = Order(
        order_id="ORD-E1-COMPTX-D4-c_diff_colitis-0",
        order_type=OrderType.MEDICATION,
        display_name="Fidaxomicin",
        drug_id="fidaxomicin",
        ordered_datetime=ONSET_ORDER,
        status=OrderStatus.PLACED,
        dose_quantity=200.0,
        dose_unit="mg",
        frequency="BID",
        frequency_per_day=2,
        route="PO",
        duration_days=10,
    )
    (spec,) = complication_discharge_specs([order], "japan", discharge_time=ONSET_ORDER + timedelta(days=4))
    assert (spec["drug_id"], spec["duration_days"], spec["from_complication"]) == ("fidaxomicin", 6, True)
