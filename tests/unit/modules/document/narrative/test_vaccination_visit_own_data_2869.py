"""Issue #2869: a vaccination visit's note prints only its own data.

The immunization enricher appends the vaccination visit (``ENC-VAX-*``,
zero-length) to the patient's first record, whose vitals, orders and
prescription belong to the record's own encounter — here an ED visit a
year later. The vaccination SOAP note printed that visit's triage vitals
("BP 107/58 ... SpO2 91%"), fired "Tachycardia" / "Hypoxemia" on them, and
listed its prescription as "Today's prescription".
"""

from __future__ import annotations

from typing import Any

import pytest

from clinosim.modules.document import specs_for_country
from clinosim.modules.document.narrative.passes import TemplateNarrativePass, scope_record_to_encounter

pytestmark = pytest.mark.unit

_ED = {
    "encounter_id": "ENC-ED-1",
    "encounter_type": "emergency",
    "admission_datetime": "2023-09-08T14:00:00",
    "discharge_datetime": "2023-09-08T18:00:00",
}
_VAX = {
    "encounter_id": "ENC-VAX-pt-1-abc",
    "encounter_type": "outpatient",
    "department_id": "primary_care",
    "admission_datetime": "2022-11-01T10:00:00",
    "discharge_datetime": "2022-11-01T10:00:00",
    "chief_complaint": "Vaccination visit",
    "admission_diagnosis_code": "Z23",
}


def _record() -> dict[str, Any]:
    return {
        "patient": {
            "patient_id": "pt-1",
            "age": 40,
            "sex": "F",
            "chronic_conditions": [],
            "current_medications": [],
            "allergies": [],
        },
        "encounters": [dict(_ED), dict(_VAX)],
        "condition_event": {},
        "clinical_diagnosis": None,
        "vital_signs": [
            {
                "timestamp": "2023-09-08T14:05:00",
                "systolic_bp": 107,
                "diastolic_bp": 58,
                "heart_rate": 130,
                "respiratory_rate": 24,
                "spo2": 91.0,
                "temperature_celsius": 37.0,
            }
        ],
        "lab_results": [{"lab_name": "CRP", "value": 8.2, "result_datetime": "2023-09-08T15:00:00"}],
        "orders": [{"order_id": "ORD-1", "encounter_id": "ENC-ED-1", "display_name": "Hydroxyzine"}],
        "medication_administrations": [{"order_id": "ORD-1", "drug_name": "Hydroxyzine", "dose": "25mg"}],
        "procedures": [{"encounter_id": "ENC-ED-1", "procedure_name": "Nebulizer treatment"}],
        "rehab_sessions": [],
        "discharge_prescription": {
            "prescription_id": "RX-1",
            "issue_date": "2023-09-08T18:00:00",
            "items": [{"drug_name": "Hydroxyzine 25mg"}],
        },
        "documents": [],
    }


def _spec(type_key: str):
    for s in specs_for_country("us"):
        if s.type_key == type_key:
            return s
    raise AssertionError(type_key)


def test_record_unchanged_for_its_own_encounter():
    rec = _record()
    assert scope_record_to_encounter(rec, rec["encounters"][0]) is rec


def test_appended_visit_sees_none_of_the_host_encounter_data():
    rec = _record()
    scoped = scope_record_to_encounter(rec, rec["encounters"][1])
    assert scoped["vital_signs"] == []
    assert scoped["lab_results"] == []
    assert scoped["orders"] == []
    assert scoped["medication_administrations"] == []
    assert scoped["procedures"] == []
    assert scoped["discharge_prescription"] is None
    # The input record is not mutated.
    assert len(rec["vital_signs"]) == 1
    assert rec["discharge_prescription"] is not None


def test_appended_visit_keeps_data_recorded_at_its_own_encounter():
    rec = _record()
    rec["vital_signs"].append({"timestamp": "2022-11-01T10:00:00", "heart_rate": 72})
    rec["orders"].append({"order_id": "ORD-2", "encounter_id": "ENC-VAX-pt-1-abc"})
    scoped = scope_record_to_encounter(rec, rec["encounters"][1])
    assert [v["heart_rate"] for v in scoped["vital_signs"]] == [72]
    assert [o["order_id"] for o in scoped["orders"]] == ["ORD-2"]


def test_vaccination_soap_note_prints_no_borrowed_vitals_or_prescription():
    rec = _record()
    p = TemplateNarrativePass(cif_dir="/nonexistent", country="US")
    spec = _spec("outpatient_soap")
    ctx = p._build_context(rec, rec["encounters"][1], spec, "en")
    assert ctx.vitals == []
    assert ctx.discharge_medications == []
    assert ctx.orders == []
    text = "\n".join(str(s) for s in p._generate(ctx, spec).sections.values())
    for borrowed in ("107/58", "130", "91", "Tachycardia", "Hypoxemia", "Hydroxyzine", "Nebulizer"):
        assert borrowed not in text, borrowed


def test_host_encounter_note_still_prints_its_vitals():
    rec = _record()
    p = TemplateNarrativePass(cif_dir="/nonexistent", country="US")
    ctx = p._build_context(rec, rec["encounters"][0], _spec("outpatient_soap"), "en")
    assert [v["heart_rate"] for v in ctx.vitals] == [130]
    assert [m["drug_name"] for m in ctx.discharge_medications] == ["Hydroxyzine 25mg"]
