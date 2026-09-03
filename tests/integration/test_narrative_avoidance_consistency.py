"""CIF↔narrative consistency: every drug mentioned in an avoidance clause
must trace to either a SafetySkipEntry (candidate) or a SafetySkipEntry
(substituted_with, which itself must be emitted as a MedicationOrder).

This is the invariant that closes `feedback_versioning_policy_cif_narrative_consistency`
for drug_safety: no narrative may invent a drug name outside the CIF trace.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

from clinosim.modules.document.narrative.template_generator import (
    _render_safety_skips_line,
)
from clinosim.modules.drug_safety.verdict import SafetySkipEntry, SafetyVerdict
from clinosim.simulator.medication_pipeline import (
    apply_drug_safety_gate_to_admission_orders,
)
from clinosim.types.encounter import Order, OrderStatus, OrderType
from clinosim.types.patient import HomeMedication, PatientProfile


def _make_med_order(drug: str, order_id: str) -> Order:
    return Order(
        order_id=order_id,
        encounter_id="ENC-1",
        patient_id="PT-1",
        order_type=OrderType.MEDICATION,
        display_name=drug,
        clinical_intent=f"First-line: {drug}",
        ordered_datetime=datetime(2026, 1, 1, 10, 0),
        ordered_by="DR-1",
        status=OrderStatus.PLACED,
    )


def _run_gate_and_render(country: str) -> tuple[list[Order], list[SafetySkipEntry], str]:
    patient = PatientProfile(patient_id="PT-1")
    patient.current_medications.append(HomeMedication(drug_name="Warfarin"))
    orders = [_make_med_order("Ibuprofen", "ORD-ENC-1-ADM-M01")]
    filtered = apply_drug_safety_gate_to_admission_orders(
        orders,
        patient,
        encounter_id="ENC-1",
        admission_time=datetime(2026, 1, 1, 10, 0),
        attending_id="DR-1",
        country=country,
    )
    # Reshape skip log to narrative-consumable dicts (mirrors context.py)
    skips_ctx = [
        {
            "considered": e.candidate_drug,
            "considered_ja": e.candidate_drug_ja,
            "avoided_due_to": e.active_conflict,
            "avoided_due_to_ja": e.active_conflict_ja,
            "substituted_with": e.substituted_with,
            "substituted_with_ja": e.substituted_with_ja,
            "context": e.context_hint,
            "severity": e.verdict.severity,
            "rationale_en": e.verdict.rationale_en,
            "rationale_ja": e.verdict.rationale_ja,
        }
        for e in patient.safety_skip_log
    ]
    lang = "ja" if country == "jp" else "en"
    rendered = _render_safety_skips_line(skips_ctx, lang)
    return filtered, patient.safety_skip_log, rendered


def _drugs_mentioned_in_rendered(text: str, drug_pool: set[str]) -> set[str]:
    """Return the subset of drug_pool that appears verbatim in text."""
    return {d for d in drug_pool if d in text}


def test_ja_narrative_avoidance_mentions_only_cif_traceable_drugs() -> None:
    filtered, skip_log, rendered = _run_gate_and_render("jp")
    assert rendered  # something was rendered
    # Universe of drug names the narrative is allowed to mention:
    #   1. candidate drugs from safety_skip_log
    #   2. substituted_with drugs from safety_skip_log (must also exist as an emitted MR)
    candidate_ja = {e.candidate_drug_ja for e in skip_log}
    substituted_ja = {e.substituted_with_ja for e in skip_log if e.substituted_with_ja}
    active_ja = {e.active_conflict_ja for e in skip_log}
    allowed = candidate_ja | substituted_ja | active_ja
    emitted_order_drugs = {o.display_name for o in filtered}

    # Every substituted drug named in narrative must be present as an emitted MR
    for entry in skip_log:
        if entry.substituted_with:
            assert entry.substituted_with in emitted_order_drugs, (
                f"substituted drug {entry.substituted_with} named in safety_skip_log but not emitted as an MR"
            )

    # Every drug name in the rendered narrative must appear in `allowed`
    # (approximate check — full linguistic parse is out of scope; we rely
    # on the deterministic template renderer's stable phrasing).
    # This is a load-bearing invariant against LLM hallucination in future
    # LLM-driven variants.
    # Bag of well-known drug names to probe against.
    probe_pool = {
        "アセトアミノフェン",
        "アスピリン",
        "イブプロフェン",
        "ワルファリン",
        "ロキソプロフェン",
        "ジクロフェナク",
        "ナプロキセン",
    }
    mentioned = _drugs_mentioned_in_rendered(rendered, probe_pool)
    for drug in mentioned:
        assert drug in allowed, (
            f"narrative mentions {drug!r} but it is not in the allowed "
            f"drug set derived from safety_skip_log ({allowed!r})"
        )


def test_en_narrative_avoidance_mentions_only_cif_traceable_drugs() -> None:
    filtered, skip_log, rendered = _run_gate_and_render("us")
    assert rendered
    candidate_en = {e.candidate_drug for e in skip_log}
    substituted_en = {e.substituted_with for e in skip_log if e.substituted_with}
    active_en = {e.active_conflict for e in skip_log}
    allowed = candidate_en | substituted_en | active_en
    emitted_order_drugs = {o.display_name for o in filtered}

    for entry in skip_log:
        if entry.substituted_with:
            assert entry.substituted_with in emitted_order_drugs

    probe_pool = {
        "Acetaminophen",
        "Aspirin",
        "Ibuprofen",
        "Warfarin",
        "Naproxen",
        "Diclofenac",
    }
    mentioned = _drugs_mentioned_in_rendered(rendered, probe_pool)
    for drug in mentioned:
        assert drug in allowed, f"narrative mentions {drug!r} but is not in allowed set {allowed!r}"
