"""FHIR MedicationRequest builder emits drug_safety notes with the
"clinosim drug_safety v1" authorReference, and does not emit DetectedIssue."""

from __future__ import annotations

from datetime import datetime


def _base_order_dict() -> dict:
    return {
        "order_id": "ORD-ENC-1-ADM-M01",
        "encounter_id": "ENC-1",
        "patient_id": "PT-1",
        "display_name": "Spironolactone",
        "urgency": "routine",
        "clinical_intent": "First-line: Spironolactone",
        "clinical_intent_ja": "初期治療: スピロノラクトン",
        "ordered_datetime": datetime(2026, 1, 1, 10, 0).isoformat(),
        "ordered_by": "DR-1",
        "status": "placed",
        "route": "PO",
        "frequency": "DAILY",
        "medication_intent": "",
    }


def test_mr_builder_passes_through_drug_safety_notes() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _build_medication_request,
    )

    order = _base_order_dict()
    order["notes"] = [
        {
            "text": "併用注意: ACEi/ARB と K 保持性利尿薬の併用は高 K 血症リスク。",
            "authorReference": {"display": "clinosim drug_safety v1"},
        }
    ]
    mr = _build_medication_request(
        order=order,
        patient_id="PT-1",
        country="jp",
        encounter_id="ENC-1",
    )
    notes = mr.get("note", [])
    assert notes, "MR builder must surface order.notes"
    matches = [n for n in notes if n.get("authorReference", {}).get("display") == "clinosim drug_safety v1"]
    assert len(matches) == 1
    assert "併用注意" in matches[0]["text"]


def test_mr_builder_ignores_empty_notes_list() -> None:
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _build_medication_request,
    )

    order = _base_order_dict()
    order["notes"] = []
    mr = _build_medication_request(
        order=order,
        patient_id="PT-1",
        country="us",
    )
    # No drug_safety note attached — note key absent OR does not carry the
    # drug_safety authorReference.
    for n in mr.get("note", []):
        assert n.get("authorReference", {}).get("display") != "clinosim drug_safety v1"


def test_mr_builder_stop_intent_and_drug_safety_note_coexist() -> None:
    """A stopped order carrying a stop-intent AND a drug_safety note gets both
    in MR.note (order matters less than presence for downstream consumers)."""
    from clinosim.modules._shared import MED_STOP_ORDER_ID_MARKER
    from clinosim.modules.output.fhir_r4.medications.medications import (
        _build_medication_request,
    )

    order = _base_order_dict()
    order["order_id"] = f"ORD-ENC-1-{MED_STOP_ORDER_ID_MARKER}-01"
    order["clinical_intent"] = "Day 2 sudden_deterioration: stop Warfarin"
    order["notes"] = [
        {
            "text": "併用注意: 別 severity finding.",
            "authorReference": {"display": "clinosim drug_safety v1"},
        }
    ]
    mr = _build_medication_request(
        order=order,
        patient_id="PT-1",
        country="jp",
        encounter_id="ENC-1",
    )
    note_texts = [n.get("text", "") for n in mr.get("note", [])]
    # Both stop-intent (F3) and drug_safety note (Issue #1066) present
    assert any("stop Warfarin" in t for t in note_texts)
    assert any("併用注意" in t for t in note_texts)
