"""A rate change of a running drug is not a drug interaction, and a
drug-condition skip names the condition (Issue #3283).

A heparin rate increase from a disease course ("Heparin
increase_rate_by_20%") went through the drug-safety gate as a new heparin
order and was blocked by ``heparin-plus-heparin`` against the running heparin,
so the notes said heparin is contraindicated with heparin. A drug-condition
verdict (``nsaid-in-heart-failure``) had no conflicting drug and rendered with
the drug-drug phrase around a blank ("avoided due to concurrent ;").
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from clinosim.locale.free_text import _split_rate_adjustment_suffix
from clinosim.modules import drug_safety
from clinosim.modules.document.narrative._safety_skips import safety_skip_line
from clinosim.modules.document.narrative.context import _build_safety_skips
from clinosim.modules.order.engine import enrich_medication_order
from clinosim.simulator.daily_loop import _gate_new_medication_orders, _start_archetype_treatments
from clinosim.simulator.medication_pipeline import apply_drug_safety_gate_to_orders
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import ChronicCondition, PatientProfile

pytestmark = pytest.mark.unit

_ADM = datetime(2026, 1, 5, 14, 0)
_DISEASES = Path("clinosim/modules/disease/reference_data")


def _med(order_id: str, name: str, day: int = 0, *, status: OrderStatus = OrderStatus.PLACED) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        display_name=name,
        ordered_datetime=_ADM + timedelta(days=day),
        status=status,
    )


def _stay(patient: PatientProfile) -> SimpleNamespace:
    return SimpleNamespace(
        encounter_id="ENC-1",
        country_key="us",
        patient=patient,
        admission_time=_ADM,
        attending_id="DR-1",
        protocol=None,
    )


_RATE_UP = {"start": {"us": [{"drug_id": "heparin", "dose": "increase_rate_by_20%", "adjusts_active": True}]}}


# --- the engine -------------------------------------------------------------


def test_same_drug_reorder_is_not_an_interaction() -> None:
    assert (
        drug_safety.check_candidate_against_active("Heparin increase_rate_by_20%", ["Heparin"], same_drug_reorder=True)
        == []
    )


def test_two_different_heparins_still_conflict() -> None:
    [verdict] = drug_safety.check_candidate_against_active("Enoxaparin 40mg SC", ["Heparin"], same_drug_reorder=True)
    assert verdict.rule_id == "heparin-plus-heparin"
    assert verdict.matched_active_drug == "Heparin"


def test_default_check_still_flags_a_duplicate_of_the_same_drug() -> None:
    # Reconciliation (duplicate statins on a home list) and prophylaxis
    # (no prophylactic heparin on top of a heparin infusion) rely on it.
    [verdict] = drug_safety.check_candidate_against_active("Heparin 5000 units SC q8h", ["Heparin"])
    assert verdict.rule_id == "heparin-plus-heparin"


# --- the order linkage and the in-stay gate ---------------------------------


def test_rate_change_links_to_the_running_order() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    running = _med("ORD-HEP", "Heparin")
    running.dose_quantity, running.dose_unit, running.route = 18.0, "U/kg/h", "IV"
    running.frequency, running.frequency_per_day = "CONTINUOUS", 24
    run = SimpleNamespace(orders=[running])
    _start_archetype_treatments(_stay(patient), run, 3, _RATE_UP)
    new = run.orders[-1]
    assert new.display_name == "Heparin increase_rate_by_20%"
    assert new.prior_order_id == "ORD-HEP"
    # Given like the order it adjusts; "20%" is the change, not a dose.
    enrich_medication_order(new)
    assert (new.dose_quantity, new.dose_unit, new.route, new.frequency, new.frequency_per_day) == (
        18.0,
        "U/kg/h",
        "IV",
        "CONTINUOUS",
        24,
    )
    assert new.drug_id == "heparin"


def test_rate_change_links_to_the_latest_running_order_only() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    run = SimpleNamespace(
        orders=[
            _med("ORD-HEP-1", "Heparin"),
            _med("ORD-STOP", "DISCONTINUE: Heparin", 1),
            _med("ORD-RIVA", "Rivaroxaban 15mg PO BID", 1),
        ]
    )
    _start_archetype_treatments(_stay(patient), run, 3, _RATE_UP)
    assert run.orders[-1].prior_order_id == "", "a stopped heparin is not running; there is nothing to adjust"
    run.orders.append(_med("ORD-HEP-2", "Heparin", 3))
    _start_archetype_treatments(_stay(patient), run, 4, _RATE_UP)
    assert run.orders[-1].prior_order_id == "ORD-HEP-2"
    # A second change adjusts the first one, now the running order.
    _start_archetype_treatments(_stay(patient), run, 5, _RATE_UP)
    assert run.orders[-1].prior_order_id == run.orders[-2].order_id


def test_start_entry_without_the_flag_is_a_new_order() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    run = SimpleNamespace(orders=[_med("ORD-HEP", "Heparin")])
    _start_archetype_treatments(_stay(patient), run, 3, {"start": {"us": [{"drug_id": "heparin"}]}})
    assert run.orders[-1].prior_order_id == ""


def test_rate_change_of_admission_heparin_passes_the_gate() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    admission = [_med("ORD-HEP", "Heparin")]
    run = SimpleNamespace(orders=list(admission))
    _start_archetype_treatments(_stay(patient), run, 3, _RATE_UP)
    kept = _gate_new_medication_orders(_stay(patient), admission, run.orders, {"ORD-HEP"})
    assert [o.display_name for o in kept] == ["Heparin", "Heparin increase_rate_by_20%"]
    assert patient.safety_skip_log == []


def test_gate_follows_the_verdict_of_an_already_accepted_prior_order() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    # Linked to an accepted order: follows it, not re-checked against it.
    change = _med("ORD-ENOX-2", "Enoxaparin 1mg/kg SC q12h", 3)
    change.prior_order_id = "ORD-ENOX"
    kept = apply_drug_safety_gate_to_orders(
        [change],
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=_ADM,
        country="us",
        already_accepted_meds=["Enoxaparin 40mg SC daily", "Heparin"],
        already_accepted_ids={"ORD-ENOX"},
    )
    assert kept == [change] and patient.safety_skip_log == []


def test_new_heparin_is_still_checked_against_running_enoxaparin() -> None:
    patient = PatientProfile(patient_id="PT-1", age=60, sex="M")
    admission = [_med("ORD-ENOX", "Enoxaparin 40mg SC daily")]
    run = SimpleNamespace(orders=list(admission))
    _start_archetype_treatments(_stay(patient), run, 3, _RATE_UP)
    kept = _gate_new_medication_orders(_stay(patient), admission, run.orders, {"ORD-ENOX"})
    assert [o.display_name for o in kept] == ["Enoxaparin 40mg SC daily"]
    [skip] = patient.safety_skip_log
    assert (skip.active_conflict, skip.verdict.rule_id) == ("Enoxaparin", "heparin-plus-heparin")


@pytest.mark.parametrize("disease", ["deep_vein_thrombosis", "pulmonary_embolism"])
def test_heparin_rate_change_entries_are_declared_adjustments(disease: str) -> None:
    data = yaml.safe_load((_DISEASES / f"{disease}.yaml").read_text(encoding="utf-8"))
    entries = [
        entry
        for arch in data["course_archetypes"].values()
        for mod in (arch.get("treatment_modifications") or {}).values()
        for country_entries in (mod.get("start") or {}).values()
        for entry in country_entries
        if entry.get("drug_id") == "heparin"
    ]
    assert entries
    for entry in entries:
        assert entry.get("adjusts_active") is True
        # The rate-change notation the display layer localizes (not translated word by word).
        assert _split_rate_adjustment_suffix(f"Heparin {entry['dose']}")[1]


# --- drug-condition verdicts name the condition -----------------------------


def test_disease_verdict_conflict_names_the_condition() -> None:
    [verdict] = drug_safety.check_candidate_against_disease_state("Ibuprofen 400mg", [("I50.9", "")])
    assert drug_safety.conflict_display(verdict) == ("heart failure", "心不全")


def test_every_disease_rule_names_its_condition() -> None:
    from clinosim.modules.drug_safety.engine import _load_disease_rules

    for rule in _load_disease_rules():
        assert rule["condition"]["en"] and rule["condition"]["ja"], rule["id"]


def _hf_patient() -> PatientProfile:
    patient = PatientProfile(patient_id="PT-1", age=70, sex="F")
    patient.chronic_conditions = [ChronicCondition(code="I50")]
    return patient


@pytest.mark.parametrize(
    ("lang", "expected"),
    [
        ("en", "- Ibuprofen 400mg avoided because of heart failure; Acetaminophen prescribed instead."),
        ("ja", "・心不全のためイブプロフェンは回避し、アセトアミノフェンを処方。"),
    ],
)
def test_nsaid_in_heart_failure_renders_the_condition(lang: str, expected: str) -> None:
    patient = _hf_patient()
    apply_drug_safety_gate_to_orders(
        [_med("ORD-IBU", "Ibuprofen 400mg")],
        patient=patient,
        encounter_id="ENC-1",
        ordered_datetime=_ADM,
        country="us",
        already_accepted_meds=[],
    )
    [skip] = _build_safety_skips(patient, SimpleNamespace(id="ENC-1"))
    assert skip["conflict_kind"] == "disease"
    assert safety_skip_line(skip, lang, prefix="safety_skips") == expected


@pytest.mark.parametrize("prefix", ["safety_skips", "safety_skips_prompt"])
@pytest.mark.parametrize("lang", ["en", "ja"])
@pytest.mark.parametrize("substituted", [None, "Acetaminophen"])
def test_disease_skip_never_renders_drug_interaction_wording(prefix: str, lang: str, substituted: str | None) -> None:
    skip = {
        "considered": "Ibuprofen",
        "considered_ja": "イブプロフェン",
        "avoided_due_to": "heart failure",
        "avoided_due_to_ja": "心不全",
        "substituted_with": substituted,
        "substituted_with_ja": "アセトアミノフェン" if substituted else None,
        "event_type": "avoid",
        "conflict_kind": "disease",
    }
    line = safety_skip_line(skip, lang, prefix=prefix)
    assert ("heart failure" if lang == "en" else "心不全") in line
    assert "concurrent" not in line and "併用" not in line, line
