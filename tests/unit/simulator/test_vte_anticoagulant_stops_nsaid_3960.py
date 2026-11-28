"""Issue #3960: a venous thromboembolism is treated, and the NSAID it interacts with is
the drug that is stopped.

A therapeutic anticoagulant ordered for a DVT / pulmonary embolism used to be skipped
by the ``anticoagulant-plus-nsaid`` rule when the patient was on an NSAID, with
acetaminophen recorded as the "alternative". The NSAID is now stopped (a stop marker
with the reason, its later doses cut, a plan line that says why) and the anticoagulant
is given; an active bleeding complication still withholds it, and the note says so.
"""

from __future__ import annotations

import pytest

from clinosim.codes.drugs import drug_classes
from clinosim.modules.document.narrative._safety_skips import safety_skip_line
from clinosim.modules.order.supersede import drop_doses_after_hold
from clinosim.simulator import daily_loop as dl
from clinosim.types.encounter import MedicationAdministration, Order, OrderStatus, OrderType
from tests.unit.simulator.test_complication_treatment_3864 import (  # noqa: F401
    ADMIT,
    ONSET_ORDER,
    _fire,
    _meds,
    _run,
    _stay,
    _weight,
)

pytestmark = pytest.mark.unit


def _home_nsaid(name: str = "Celecoxib", order_id: str = "ORD-E1-HM-01") -> Order:
    return Order(
        order_id=order_id,
        encounter_id="E1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=ADMIT,
        status=OrderStatus.PLACED,
        dose_quantity=100.0,
        dose_unit="mg",
        frequency="BID",
        frequency_per_day=2,
        route="PO",
    )


def _with_nsaid(country: str, name: str = "Celecoxib"):
    stay = _stay(country)
    stay.patient.current_medications = [_med(name)]
    return stay, _run([_home_nsaid(name)], creatinine=0.9)


def _med(name: str):
    from clinosim.types.patient import HomeMedication

    return HomeMedication(drug_name=name)


def _stops(run):
    return [o for o in run.orders if o.display_name.startswith("DISCONTINUE:")]


@pytest.mark.parametrize(
    ("country", "nsaid", "anticoagulants"),
    [("japan", "Celecoxib", {"heparin", "edoxaban"}), ("japan", "Loxoprofen", {"heparin", "edoxaban"})]
    + [("us", "Ibuprofen", {"rivaroxaban"})],
)
@pytest.mark.parametrize("complication", ["dvt", "pulmonary_embolism"])
def test_the_anticoagulant_is_ordered_and_the_nsaid_stopped(monkeypatch, country, nsaid, anticoagulants, complication):
    stay, run = _with_nsaid(country, nsaid)
    _fire(monkeypatch, stay, run, complication)
    assert {o.drug_id for o in _meds(run, "anticoagulant")} == anticoagulants
    (stop,) = _stops(run)
    assert stop.display_name == f"DISCONTINUE: {nsaid}"
    assert "-STOP-" in stop.order_id and "-COMPHOLD-" in stop.order_id
    assert stop.ordered_datetime == ONSET_ORDER
    assert dl._running_order(run.orders, nsaid) is None
    assert "NSAID stopped" in stop.clinical_intent and "anticoagulation" in stop.clinical_intent
    assert "NSAID" in stop.clinical_intent_ja and "抗凝固" in stop.clinical_intent_ja
    # nothing is skipped or swapped for an analgesic
    assert [e for e in stay.patient.safety_skip_log if e.event_type == "avoid"] == []
    assert not any("cetaminophen" in (o.display_name or "") for o in run.orders)


def test_the_stopped_nsaids_doses_are_cut_from_the_stop_time(monkeypatch) -> None:
    stay, run = _with_nsaid("japan")
    _fire(monkeypatch, stay, run)
    home = run.orders[0]
    doses = [
        MedicationAdministration(order_id=home.order_id, drug_name="Celecoxib", scheduled_datetime=when)
        for when in (
            ONSET_ORDER.replace(hour=9),
            ONSET_ORDER.replace(hour=21),
            ONSET_ORDER.replace(day=ONSET_ORDER.day + 1),
        )
    ]
    kept = drop_doses_after_hold(run.orders, doses)
    assert [m.scheduled_datetime.hour for m in kept] == [9]
    assert home.end_datetime == ONSET_ORDER


def test_the_plan_line_says_the_nsaid_was_stopped_because_of_the_anticoagulation(monkeypatch) -> None:
    for country, lang, expected in (
        ("us", "en", "was discontinued"),
        ("japan", "ja", "中止"),
    ):
        stay, run = _with_nsaid(country)
        _fire(monkeypatch, stay, run)
        (entry,) = [e for e in stay.patient.safety_skip_log if e.candidate_drug.startswith("Celecoxib")]
        skip = {
            "event_type": entry.event_type,
            "considered": entry.candidate_drug,
            "considered_ja": entry.candidate_drug_ja,
            "avoided_due_to": entry.active_conflict,
            "avoided_due_to_ja": entry.active_conflict_ja,
            "stopped_on_day": entry.stopped_on_day,
        }
        line = safety_skip_line(skip, lang, prefix="safety_skips")
        assert expected in line
        assert ("anticoagulation" in line) if lang == "en" else ("抗凝固" in line)
        assert "cetaminophen" not in line and "アセトアミノフェン" not in line
        assert entry.stopped_on_day == (ONSET_ORDER.date() - ADMIT.date()).days + 1  # the hospital day of the onset


def test_aspirin_is_not_stopped_for_the_anticoagulant(monkeypatch) -> None:
    """Aspirin is an NSAID by class only; with an anticoagulant it is an antiplatelet question."""
    stay = _stay("japan")
    stay.patient.current_medications = [_med("Aspirin")]
    run = _run([_home_nsaid("Aspirin")], creatinine=0.9)
    _fire(monkeypatch, stay, run)
    assert not _stops(run)
    assert "antiplatelet" in drug_classes("Aspirin")


def test_an_nsaid_that_was_not_running_blocks_nothing(monkeypatch) -> None:
    """A home NSAID the admission held has no running order: nothing to stop, and it no longer blocks."""
    stay = _stay("japan")
    stay.patient.current_medications = [_med("Celecoxib")]
    run = _run(creatinine=0.9)
    _fire(monkeypatch, stay, run)
    assert {o.drug_id for o in _meds(run, "anticoagulant")} == {"heparin", "edoxaban"}
    assert not _stops(run)


@pytest.mark.parametrize("bleed", ["hemorrhagic_transformation", "gi_bleeding"])
def test_an_active_bleed_still_withholds_the_anticoagulant_and_the_note_says_so(monkeypatch, bleed) -> None:
    stay, run = _with_nsaid("japan")
    run.active_complications = {bleed}
    _fire(monkeypatch, stay, run)
    assert not _meds(run, "anticoagulant")
    assert not _stops(run), "the NSAID is not stopped for an anticoagulant that is not given"
    (entry,) = [e for e in stay.patient.safety_skip_log if e.event_type == "hold"]
    assert entry.candidate_drug in {"Heparin", "Edoxaban"}
    line_en = safety_skip_line(
        {"event_type": "hold", "considered": entry.candidate_drug, "avoided_due_to": entry.active_conflict},
        "en",
        prefix="safety_skips",
    )
    assert "bleeding" in line_en or "hemorrhag" in line_en
    assert "ヘパリン" in entry.candidate_drug_ja or "エドキサバン" in entry.candidate_drug_ja
    assert entry.active_conflict_ja and not entry.active_conflict_ja.isascii()


def test_prophylaxis_keeps_the_skip_for_an_nsaid() -> None:
    """The prophylactic dose is still gated by the rule (the issue's scope is the therapeutic order)."""
    from clinosim.modules import drug_safety

    v = drug_safety.check_pair("Enoxaparin", "Celecoxib")
    assert v.rule_id == "anticoagulant-plus-nsaid" and v.severity == "contraindicated"


def test_the_discharge_prescription_keeps_the_anticoagulant_and_not_the_nsaid(monkeypatch) -> None:
    import numpy as np

    from clinosim.modules.disease.protocol import load_disease_protocol
    from clinosim.simulator.complication_actions import complication_discharge_specs
    from clinosim.simulator.discharge_rx import build_discharge_rx

    stay, run = _with_nsaid("japan")
    _fire(monkeypatch, stay, run)
    specs = complication_discharge_specs(run.orders, "japan")
    assert [s["drug_id"] for s in specs] == ["edoxaban"]
    rx = build_discharge_rx(
        stay.patient,
        "bacterial_pneumonia",
        load_disease_protocol("bacterial_pneumonia"),
        "DR1",
        ADMIT,
        np.random.default_rng(0),
        encounter_id="E1",
        country_key="japan",
        extra_specs=specs,
    )
    names = [i["drug_name"] for i in rx.items]
    assert "Edoxaban" in names and "Celecoxib" not in names


def test_the_later_gate_of_the_stays_new_orders_keeps_the_anticoagulant(monkeypatch) -> None:
    """The daily loop gates every order added after admission once more, against the admission
    orders: the stopped NSAID (an admission order) must not count as active there, and the
    stop marker must not stand in for it (it names the drug but gives none)."""
    stay, run = _with_nsaid("japan")
    _fire(monkeypatch, stay, run)
    admission = [run.orders[0]]
    kept = dl._gate_new_medication_orders(stay, admission, run.orders, {admission[0].order_id})
    assert {
        o.drug_id
        for o in kept
        if o.order_type == OrderType.MEDICATION and "anticoagulant" in drug_classes(o.drug_id or o.display_name)
    } == {
        "heparin",
        "edoxaban",
    }
    assert [e for e in stay.patient.safety_skip_log if e.event_type == "avoid"] == []
    assert any(o.display_name == "DISCONTINUE: Celecoxib" for o in kept)


def test_a_stop_marker_is_neither_checked_nor_active_in_the_pair_rules() -> None:
    from clinosim.modules import drug_safety

    assert drug_safety.check_candidate_against_active("Heparin", ["DISCONTINUE: Celecoxib"]) == []
    assert drug_safety.check_candidate_against_active("DISCONTINUE: Celecoxib", ["Heparin"]) == []
    assert drug_safety.check_candidate_against_active("Heparin", ["Celecoxib"])
