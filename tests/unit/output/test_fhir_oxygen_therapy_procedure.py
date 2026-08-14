"""Unit tests for `procedures/oxygen_therapy.py` — oxygen-therapy session
Procedure emission with performedPeriod, SNOMED coding, and no bodySite
placeholder.

Report P1-8: oxygen therapy is a session, not a point in time; the
generic `_bb_procedures` order-derived path emits only performedDateTime
and stuffs the SpO2 target into code.text with a "処置部位不明" bodySite
placeholder. This builder replaces that shape with:

- SNOMED CT 57485005 coding on Procedure.code
- performedPeriod derived from on-supplemental-oxygen vitals
- SpO2 target in note[], not code.text
- usedCode carrying the delivery device SNOMED (e.g. nasal cannula)
- no bodySite (concept is irrelevant for oxygen therapy)
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from clinosim.modules.output.fhir_r4.procedures.oxygen_therapy import (
    _bb_oxygen_therapy,
    is_oxygen_order,
)

pytestmark = pytest.mark.unit


def _ctx(record: dict, country: str = "JP", patient_id: str = "POP-TEST"):
    return SimpleNamespace(
        record=record,
        country=country,
        patient_id=patient_id,
        roster_map={},
        hospital_config={},
        patient_data={},
        is_readmission=False,
        prior_encounter_id=None,
        primary_dx_code="",
        admit_dx_code="",
        admit_dx_system="",
        primary_enc_id="",
        patient_sex="M",
    )


def _record_with_o2_session(
    encounter_id: str = "ENC-1",
    order_id: str = "ORD-ENC-1-ADM-S00",
    encounter_discharge: str = "2025-06-30T20:00:00",
    device: str = "nasal_cannula",
    display_name: str = "O2: Nasal cannula SpO2 >= 94%",
    on_o2_vital_count: int = 3,
    ordered_by: str = "DR-IM-001",
) -> dict:
    """Build a minimal CIF record with a single O2 order + N on-O2 vitals."""
    vital_timestamps = [
        "2025-06-21T18:22:00",
        "2025-06-25T12:00:00",
        "2025-06-30T20:00:00",
    ][:on_o2_vital_count]
    return {
        "encounters": [
            {"encounter_id": encounter_id, "discharge_datetime": encounter_discharge},
        ],
        "orders": [
            {
                "order_id": order_id,
                "encounter_id": encounter_id,
                "order_type": "procedure",
                "display_name": display_name,
                "ordered_datetime": "2025-06-21T18:26:00",
                "ordered_by": ordered_by,
            }
        ],
        "vital_signs": [
            {
                "encounter_id": encounter_id,
                "timestamp": ts,
                "on_supplemental_oxygen": True,
                "oxygen_delivery_device": device,
            }
            for ts in vital_timestamps
        ],
    }


def test_is_oxygen_order_matches_display_prefix():
    assert is_oxygen_order({"display_name": "O2: Nasal cannula SpO2 >= 94%"})
    assert is_oxygen_order({"display_name": "O2 Nasal cannula"})
    assert not is_oxygen_order({"display_name": "Nebulizer treatment"})
    assert not is_oxygen_order({"display_name": ""})


def test_procedure_has_performed_period_from_vitals():
    """Session period spans the first + last on-O2 vital timestamps."""
    ctx = _ctx(_record_with_o2_session(on_o2_vital_count=3))
    resources = _bb_oxygen_therapy(ctx)
    assert len(resources) == 1
    p = resources[0]
    assert p["resourceType"] == "Procedure"
    assert "performedPeriod" in p
    # first vital was 2025-06-21T18:22; order was 18:26 → session picks earlier one
    assert p["performedPeriod"]["start"].startswith("2025-06-21T18:22:00")
    # Last on-O2 vital equals the last recorded vital → session end = encounter discharge
    assert p["performedPeriod"]["end"].startswith("2025-06-30T20:00:00")


def test_procedure_carries_snomed_oxygen_therapy_coding():
    ctx = _ctx(_record_with_o2_session())
    p = _bb_oxygen_therapy(ctx)[0]
    coding = p["code"]["coding"][0]
    assert coding["system"] == "http://snomed.info/sct"
    assert coding["code"] == "57485005"
    assert coding["display"], "display should be resolved via code_lookup"


def test_procedure_code_text_is_clean_no_target_or_device():
    """code.text must be the clean localised label — no "SpO2 >= 94%" and
    no "Nasal cannula" contamination (moved to note[] and usedCode[])."""
    ctx = _ctx(_record_with_o2_session())
    p = _bb_oxygen_therapy(ctx)[0]
    assert p["code"]["text"] == "酸素投与"
    assert "SpO2" not in p["code"]["text"]
    assert "Nasal" not in p["code"]["text"]
    assert "cannula" not in p["code"]["text"]


def test_procedure_no_body_site():
    """bodySite is not emitted — oxygen therapy has no anatomical concept
    and the "処置部位不明" placeholder is misleading."""
    ctx = _ctx(_record_with_o2_session())
    p = _bb_oxygen_therapy(ctx)[0]
    assert "bodySite" not in p


def test_procedure_note_carries_spo2_target():
    ctx = _ctx(_record_with_o2_session(display_name="O2: Nasal cannula SpO2 >= 94%"))
    p = _bb_oxygen_therapy(ctx)[0]
    notes = p.get("note", [])
    assert len(notes) == 1
    assert "SpO2 >= 94%" in notes[0]["text"]
    assert "投与目標" in notes[0]["text"]  # JP text


def test_procedure_usedcode_carries_device_snomed():
    ctx = _ctx(_record_with_o2_session(device="nasal_cannula"))
    p = _bb_oxygen_therapy(ctx)[0]
    used = p.get("usedCode", [])
    assert len(used) == 1
    coding = used[0]["coding"][0]
    assert coding["system"] == "http://snomed.info/sct"
    assert coding["code"] == "336623009"  # nasal cannula
    assert coding["display"] == "経鼻カニューラ"


def test_ventilator_maps_to_ventilator_snomed():
    ctx = _ctx(_record_with_o2_session(device="ventilator"))
    p = _bb_oxygen_therapy(ctx)[0]
    coding = p["usedCode"][0]["coding"][0]
    assert coding["code"] == "26412008"


def test_no_emission_when_no_on_o2_vitals():
    """Order exists but the patient never went on O2 per vitals → skip."""
    record = _record_with_o2_session()
    for v in record["vital_signs"]:
        v["on_supplemental_oxygen"] = False
    ctx = _ctx(record)
    resources = _bb_oxygen_therapy(ctx)
    assert resources == []


def test_procedure_emitted_from_vitals_only_when_no_o2_order():
    """Session 88j coverage fix: encounters with on-O2 vitals but no explicit
    O2 Order still emit a Procedure derived from vitals alone. This closes
    the ~34% coverage gap where non-respiratory disease patients (stroke,
    DKA, pyelonephritis, …) receive supplemental O2 via SpO2-driven vitals
    but the disease-YAML supportive_care never placed an O2 Order."""
    record = _record_with_o2_session()
    record["orders"] = []
    record["encounters"][0]["attending_physician_id"] = "DR-IM-777"
    ctx = _ctx(record)
    resources = _bb_oxygen_therapy(ctx)
    assert len(resources) == 1
    p = resources[0]
    # Start = first on-O2 vital (no order to compare against)
    assert p["performedPeriod"]["start"].startswith("2025-06-21T18:22:00")
    # SNOMED coding still present
    assert p["code"]["coding"][0]["code"] == "57485005"
    # No SpO2 target note (no Order carried one)
    assert "note" not in p
    # Performer falls back to encounter attending
    assert p["performer"] == [{"actor": {"reference": "Practitioner/DR-IM-777"}}]
    # Procedure id derived from encounter (no order_id available)
    assert p["id"] == "proc-o2-ENC-1"
    # Device still emitted from vitals
    assert p["usedCode"][0]["coding"][0]["code"] == "336623009"


def test_no_emission_when_no_on_o2_vitals_and_no_order():
    """Neither Order nor on-O2 vitals → nothing to emit."""
    record = _record_with_o2_session()
    record["orders"] = []
    for v in record["vital_signs"]:
        v["on_supplemental_oxygen"] = False
    ctx = _ctx(record)
    assert _bb_oxygen_therapy(ctx) == []


def test_vitals_only_omits_performer_when_no_attending():
    """Vitals-only path with no attending_physician_id on the encounter →
    Procedure emitted without a performer element (not a fabricated one)."""
    record = _record_with_o2_session()
    record["orders"] = []
    # encounter has no attending_physician_id set
    ctx = _ctx(record)
    p = _bb_oxygen_therapy(ctx)[0]
    assert "performer" not in p


def test_multiple_orders_per_encounter_deduplicated():
    """If two O2 Orders exist on the same encounter (theoretical titration
    scenario), only one Procedure is emitted with the earliest ordered_dt."""
    record = _record_with_o2_session()
    record["orders"].append(
        {
            "order_id": "ORD-ENC-1-ADM-S01",
            "encounter_id": "ENC-1",
            "order_type": "procedure",
            "display_name": "O2: Simple mask SpO2 >= 92%",
            "ordered_datetime": "2025-06-25T09:00:00",
            "ordered_by": "DR-IM-002",
        }
    )
    ctx = _ctx(record)
    resources = _bb_oxygen_therapy(ctx)
    assert len(resources) == 1
    # earliest Order's ordered_by wins for performer attribution
    assert resources[0]["performer"] == [{"actor": {"reference": "Practitioner/DR-IM-001"}}]


def test_procedure_encounter_reference_and_reason():
    ctx = _ctx(_record_with_o2_session(encounter_id="ENC-XYZ"))
    p = _bb_oxygen_therapy(ctx)[0]
    assert p["encounter"] == {"reference": "Encounter/ENC-XYZ"}
    assert p["reasonReference"] == [{"reference": "Condition/cond-ENC-XYZ-primary"}]


def test_procedure_performer_from_order_ordered_by():
    ctx = _ctx(_record_with_o2_session(ordered_by="DR-ATTND-42"))
    p = _bb_oxygen_therapy(ctx)[0]
    assert p["performer"] == [{"actor": {"reference": "Practitioner/DR-ATTND-42"}}]


def test_us_locale_english_text():
    ctx = _ctx(_record_with_o2_session(display_name="O2: Nasal cannula SpO2 >= 94%"), country="US")
    p = _bb_oxygen_therapy(ctx)[0]
    assert p["code"]["text"] == "Oxygen therapy"
    assert p["note"][0]["text"].startswith("Target:")
    assert p["usedCode"][0]["coding"][0]["display"] == "Nasal cannula"


def test_jp_profile_present_on_jp_output():
    ctx = _ctx(_record_with_o2_session(), country="JP")
    p = _bb_oxygen_therapy(ctx)[0]
    assert "http://jpfhir.jp/fhir/core/StructureDefinition/JP_Procedure" in p["meta"]["profile"]


def test_session_end_uses_last_on_o2_when_patient_weaned_before_discharge():
    """If the last on-O2 vital is not the last recorded vital, the session
    end is the last on-O2 timestamp (patient was weaned before discharge)."""
    record = {
        "encounters": [{"encounter_id": "ENC-1", "discharge_datetime": "2025-06-30T20:00:00"}],
        "orders": [
            {
                "order_id": "ORD-1",
                "encounter_id": "ENC-1",
                "order_type": "procedure",
                "display_name": "O2: Nasal cannula",
                "ordered_datetime": "2025-06-21T18:00:00",
            }
        ],
        "vital_signs": [
            {
                "encounter_id": "ENC-1",
                "timestamp": "2025-06-21T18:00:00",
                "on_supplemental_oxygen": True,
                "oxygen_delivery_device": "nasal_cannula",
            },
            {
                "encounter_id": "ENC-1",
                "timestamp": "2025-06-25T12:00:00",
                "on_supplemental_oxygen": True,
                "oxygen_delivery_device": "nasal_cannula",
            },
            # patient weaned — later vital shows off O2
            {
                "encounter_id": "ENC-1",
                "timestamp": "2025-06-30T20:00:00",
                "on_supplemental_oxygen": False,
                "oxygen_delivery_device": "",
            },
        ],
    }
    ctx = _ctx(record)
    p = _bb_oxygen_therapy(ctx)[0]
    # last on-O2 vital was 2025-06-25T12:00 → session ends there, not at discharge
    assert p["performedPeriod"]["end"].startswith("2025-06-25T12:00:00")
